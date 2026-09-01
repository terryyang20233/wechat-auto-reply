#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#import <Cocoa/Cocoa.h>
#include <ApplicationServices/ApplicationServices.h>
#include <Python.h>

#define URL "http://127.0.0.1:8765"

static int run_cmd(const char *cmd) {
    return system(cmd) == 0;
}

static int health_ok(void) {
    return run_cmd("/usr/bin/curl -sf --max-time 0.6 '" URL "/api/health' >/dev/null 2>&1");
}

static void open_browser(void) {
    run_cmd("/usr/bin/open '" URL "'");
}

static int read_trimmed(const char *path, char *out, size_t n) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        return 0;
    }
    if (!fgets(out, (int)n, fp)) {
        fclose(fp);
        return 0;
    }
    fclose(fp);
    size_t len = strlen(out);
    while (len > 0 && (out[len - 1] == '\n' || out[len - 1] == '\r' || out[len - 1] == ' ')) {
        out[--len] = '\0';
    }
    return len > 0;
}

static int executable_path(char *out, size_t n) {
    uint32_t size = (uint32_t)n;
    if (_NSGetExecutablePath(out, &size) != 0) {
        return 0;
    }
    char real[PATH_MAX];
    if (!realpath(out, real)) {
        return 0;
    }
    if (strlen(real) + 1 > n) {
        return 0;
    }
    memcpy(out, real, strlen(real) + 1);
    return 1;
}

static int dirname_of(char *path) {
    char *slash = strrchr(path, '/');
    if (!slash) {
        return 0;
    }
    if (slash == path) {
        slash[1] = '\0';
        return 1;
    }
    *slash = '\0';
    return 1;
}

static int resolve_root(char *out, size_t n) {
    char exe[PATH_MAX];
    if (!executable_path(exe, sizeof(exe))) {
        return 0;
    }
    char dir[PATH_MAX];
    snprintf(dir, sizeof(dir), "%s", exe);
    if (!dirname_of(dir)) {
        return 0;
    }
    char bundled[PATH_MAX];
    snprintf(bundled, sizeof(bundled), "%s/../Resources/project-root", dir);
    char root[PATH_MAX];
    if (read_trimmed(bundled, root, sizeof(root))) {
        char real[PATH_MAX];
        if (realpath(root, real) && strlen(real) + 1 <= n) {
            memcpy(out, real, strlen(real) + 1);
            return 1;
        }
    }
    return 0;
}

static int read_pyvenv_home(const char *root, char *home, size_t n) {
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/.venv/pyvenv.cfg", root);
    FILE *fp = fopen(path, "r");
    if (!fp) {
        return 0;
    }
    char line[PATH_MAX];
    int ok = 0;
    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "home", 4) != 0) {
            continue;
        }
        char *eq = strchr(line, '=');
        if (!eq) {
            continue;
        }
        eq++;
        while (*eq == ' ') {
            eq++;
        }
        size_t len = strlen(eq);
        while (len > 0 && (eq[len - 1] == '\n' || eq[len - 1] == '\r' || eq[len - 1] == ' ')) {
            eq[--len] = '\0';
        }
        if (len + 1 > n) {
            break;
        }
        memcpy(home, eq, len + 1);
        ok = 1;
        break;
    }
    fclose(fp);
    if (!ok) {
        return 0;
    }
    size_t hlen = strlen(home);
    if (hlen >= 4 && strcmp(home + hlen - 4, "/bin") == 0) {
        home[hlen - 4] = '\0';
    }
    return 1;
}

static int find_site_packages(const char *root, char *out, size_t n) {
    char lib[PATH_MAX];
    snprintf(lib, sizeof(lib), "%s/.venv/lib", root);
    DIR *d = opendir(lib);
    if (!d) {
        return 0;
    }
    struct dirent *ent;
    int ok = 0;
    while ((ent = readdir(d)) != NULL) {
        if (strncmp(ent->d_name, "python", 6) != 0) {
            continue;
        }
        int written = snprintf(out, n, "%s/.venv/lib/%s/site-packages", root, ent->d_name);
        if (written > 0 && (size_t)written < n) {
            ok = 1;
            break;
        }
    }
    closedir(d);
    return ok;
}

static void redirect_logs(void) {
    const char *home = getenv("HOME");
    if (!home) {
        return;
    }
    char dir[512];
    char path[576];
    snprintf(dir, sizeof(dir), "%s/.wechat-assist", home);
    snprintf(path, sizeof(path), "%s/server.log", dir);
    mkdir(dir, 0700);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }
}

static int run_embedded_python(const char *root) {
    char home[PATH_MAX];
    char site[PATH_MAX];
    char src[PATH_MAX];
    char pythonpath[PATH_MAX * 2];
    if (!read_pyvenv_home(root, home, sizeof(home))) {
        fprintf(stderr, "missing .venv/pyvenv.cfg\n");
        return 127;
    }
    if (!find_site_packages(root, site, sizeof(site))) {
        fprintf(stderr, "missing venv site-packages\n");
        return 127;
    }
    snprintf(src, sizeof(src), "%s/src", root);
    snprintf(pythonpath, sizeof(pythonpath), "%s:%s", src, site);
    fprintf(stderr, "python home=%s site=%s\n", home, site);
    setenv("PYTHONHOME", home, 1);
    setenv("PYTHONPATH", pythonpath, 1);
    unsetenv("VIRTUAL_ENV");
    unsetenv("PYTHONEXECUTABLE");
    if (chdir(root) != 0) {
        fprintf(stderr, "chdir failed: %s\n", root);
        return 127;
    }

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    status = PyConfig_SetBytesString(&config, &config.home, home);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        return 127;
    }
    status = PyConfig_SetBytesString(&config, &config.run_module, "wechat_assist");
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        return 127;
    }
    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        return 127;
    }
    return Py_RunMain();
}

static pid_t server_pid_from_http(void) {
    FILE *fp = popen(
        "/usr/bin/curl -sf --max-time 0.8 '" URL "/api/status' "
        "| /usr/bin/grep -Eo '\"pid\":[[:space:]]*[0-9]+' "
        "| /usr/bin/head -1 "
        "| /usr/bin/tr -dc '0-9'",
        "r");
    if (!fp) {
        return 0;
    }
    char buf[32] = {0};
    if (!fgets(buf, sizeof(buf), fp)) {
        pclose(fp);
        return 0;
    }
    pclose(fp);
    return (pid_t)atoi(buf);
}

static void stop_foreign_servers(void) {
    pid_t me = getpid();
    pid_t old = server_pid_from_http();
    if (old > 1 && old != me) {
        kill(old, SIGTERM);
        for (int i = 0; i < 20 && health_ok(); i++) {
            usleep(100000);
        }
        if (health_ok()) {
            kill(old, SIGKILL);
            usleep(150000);
        }
    }
    FILE *fp = popen("/usr/bin/pgrep -x WeChatAssist; /usr/bin/pgrep -x wechat-assist-server", "r");
    if (!fp) {
        return;
    }
    char line[32];
    while (fgets(line, sizeof(line), fp)) {
        pid_t pid = (pid_t)atoi(line);
        if (pid > 1 && pid != me) {
            kill(pid, SIGTERM);
        }
    }
    pclose(fp);
    usleep(150000);
}

static void hide_from_dock(void) {
    ProcessSerialNumber psn = {0, kCurrentProcess};
    TransformProcessType(&psn, kProcessTransformToBackgroundApplication);
}

static int run_server_mode(void) {
    hide_from_dock();
    redirect_logs();
    char root[PATH_MAX];
    if (!resolve_root(root, sizeof(root))) {
        fprintf(stderr, "missing project-root\n");
        return 127;
    }
    return run_embedded_python(root);
}

static void install_menu(void) {
    NSMenu *menubar = [[NSMenu alloc] init];
    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [menubar addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"微信回复助手"];
    NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"退出微信回复助手"
                                             action:@selector(terminate:)
                                      keyEquivalent:@"q"];
    [quit setTarget:NSApp];
    [appMenu addItem:quit];
    [appItem setSubmenu:appMenu];
    [NSApp setMainMenu:menubar];
}

@interface AppDelegate : NSObject <NSApplicationDelegate>
@property (nonatomic, strong) NSTask *serverTask;
@property (nonatomic, assign) BOOL stopping;
@end

@implementation AppDelegate

- (pid_t)serverPid {
    if (self.serverTask && self.serverTask.isRunning) {
        return self.serverTask.processIdentifier;
    }
    return 0;
}

- (void)killServer {
    NSTask *task = self.serverTask;
    self.serverTask = nil;
    if (task && task.isRunning) {
        pid_t pid = task.processIdentifier;
        [task terminate];
        for (int i = 0; i < 20 && kill(pid, 0) == 0; i++) {
            usleep(50000);
        }
        if (kill(pid, 0) == 0) {
            kill(pid, SIGKILL);
        }
    }
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    [[NSProcessInfo processInfo] disableSuddenTermination];
    [NSApp activateIgnoringOtherApps:NO];

    char root[PATH_MAX];
    if (!resolve_root(root, sizeof(root))) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"微信回复助手";
        alert.informativeText = @"找不到项目目录。请在项目里重新运行 scripts/install-app.sh。";
        [alert runModal];
        [NSApp terminate:nil];
        return;
    }
    char venv_python[PATH_MAX];
    snprintf(venv_python, sizeof(venv_python), "%s/.venv/bin/python", root);
    if (access(venv_python, X_OK) != 0) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"微信回复助手";
        alert.informativeText = @"还没有安装运行环境。请先执行 pip install -e \".[macos]\"。";
        [alert runModal];
        [NSApp terminate:nil];
        return;
    }

    stop_foreign_servers();

    char exe[PATH_MAX];
    char helper[PATH_MAX];
    if (!executable_path(exe, sizeof(exe))) {
        [NSApp terminate:nil];
        return;
    }
    snprintf(helper, sizeof(helper), "%s", exe);
    char *slash = strrchr(helper, '/');
    if (!slash) {
        [NSApp terminate:nil];
        return;
    }
    *slash = '\0';
    if (!dirname_of(helper)) {
        [NSApp terminate:nil];
        return;
    }
    char helperPath[PATH_MAX];
    snprintf(helperPath, sizeof(helperPath), "%s/Helpers/wechat-assist-server", helper);
    if (access(helperPath, X_OK) != 0) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"微信回复助手";
        alert.informativeText = @"缺少 wechat-assist-server。请重新运行 scripts/install-app.sh。";
        [alert runModal];
        [NSApp terminate:nil];
        return;
    }

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:@(helperPath)];
    task.arguments = @[@"--server"];
    task.terminationHandler = ^(NSTask *finished) {
        (void)finished;
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!self.stopping) {
                [NSApp terminate:nil];
            }
        });
    };
    NSError *err = nil;
    if (![task launchAndReturnError:&err]) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"微信回复助手";
        alert.informativeText = err.localizedDescription ?: @"启动失败。";
        [alert runModal];
        [NSApp terminate:nil];
        return;
    }
    self.serverTask = task;

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        for (int i = 0; i < 40; i++) {
            if (health_ok()) {
                open_browser();
                return;
            }
            if (!self.serverTask.isRunning) {
                return;
            }
            usleep(250000);
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"微信回复助手";
            alert.informativeText = @"助手启动超时。可查看 ~/.wechat-assist/server.log";
            [alert runModal];
            [NSApp terminate:nil];
        });
    });
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    (void)sender;
    (void)flag;
    open_browser();
    return NO;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    self.stopping = YES;
    [self killServer];
    return NSTerminateNow;
}

@end

int main(int argc, const char *argv[]) {
    if (argc > 1 && strcmp(argv[1], "--server") == 0) {
        return run_server_mode();
    }

    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        install_menu();
        AppDelegate *delegate = [AppDelegate new];
        [NSApp setDelegate:delegate];
        [NSApp run];
    }
    return 0;
}
