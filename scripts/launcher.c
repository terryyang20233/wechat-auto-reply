#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <ApplicationServices/ApplicationServices.h>
#include <CoreFoundation/CoreFoundation.h>

#ifndef ROOT_DIR
#error ROOT_DIR is required
#endif
#ifndef PYTHON_BIN
#error PYTHON_BIN is required
#endif

#define URL "http://127.0.0.1:8765"

static pid_t child_pid = 0;

static void forward_signal(int sig) {
    if (child_pid > 0) {
        kill(child_pid, sig);
    }
}

static int run_cmd(const char *cmd) {
    int rc = system(cmd);
    return rc == 0;
}

static int health_ok(void) {
    return run_cmd("/usr/bin/curl -sf --max-time 0.6 '" URL "/api/health' >/dev/null 2>&1");
}

static int ax_trusted(void) {
    return run_cmd(
        "/usr/bin/curl -sf --max-time 0.8 '" URL "/api/status' "
        "| /usr/bin/grep -Eq '\"ax_trusted\":[[:space:]]*true'");
}

static pid_t server_pid(void) {
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

static void open_browser(void) {
    run_cmd("/usr/bin/open '" URL "'");
}

static void open_ax_settings(void) {
    run_cmd(
        "/usr/bin/open "
        "'x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility'");
}

static void request_ax(void) {
    const void *keys[] = {kAXTrustedCheckOptionPrompt};
    const void *vals[] = {kCFBooleanTrue};
    CFDictionaryRef opts = CFDictionaryCreate(
        kCFAllocatorDefault,
        keys,
        vals,
        1,
        &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    if (opts) {
        AXIsProcessTrustedWithOptions(opts);
        CFRelease(opts);
    }
}

static int is_ax_trusted_now(void) {
    return AXIsProcessTrusted();
}

static void alert(const char *text) {
    char cmd[2048];
    snprintf(
        cmd,
        sizeof(cmd),
        "/usr/bin/osascript -e 'display dialog \"%s\" buttons {\"好\"} default button 1 "
        "with title \"微信回复助手\"'",
        text);
    run_cmd(cmd);
}

static void stop_old_server(void) {
    pid_t old = server_pid();
    if (old <= 1) {
        return;
    }
    kill(old, SIGTERM);
    for (int i = 0; i < 25 && health_ok(); i++) {
        usleep(100000);
    }
    if (health_ok()) {
        kill(old, SIGKILL);
        usleep(200000);
    }
}

static void redirect_child_logs(void) {
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

int main(void) {
    if (health_ok() && ax_trusted()) {
        open_browser();
        return 0;
    }
    if (health_ok()) {
        stop_old_server();
    }

    if (access(PYTHON_BIN, X_OK) != 0) {
        alert("还没有安装运行环境。请先在项目目录执行 pip install。");
        return 1;
    }

    request_ax();
    if (!is_ax_trusted_now()) {
        open_ax_settings();
        run_cmd(
            "/usr/bin/osascript -e "
            "'display dialog \"关掉 Cursor 后，需要给「微信回复助手」辅助功能权限（和勾选 Cursor 是同一类开关）。\" "
            "& return & return & "
            "\"请在系统设置里找到「微信回复助手」并打开开关。若没有，点左下角「+」添加本程序。打开后再点「好」。\" "
            "buttons {\"好\"} default button 1 with title \"微信回复助手\"'");
        request_ax();
    }

    signal(SIGINT, forward_signal);
    signal(SIGTERM, forward_signal);
    signal(SIGHUP, forward_signal);

    pid_t pid = fork();
    if (pid == 0) {
        redirect_child_logs();
        if (chdir(ROOT_DIR) != 0) {
            _exit(127);
        }
        execl(PYTHON_BIN, PYTHON_BIN, "-m", "wechat_assist", (char *)NULL);
        _exit(127);
    }
    if (pid < 0) {
        alert("启动失败。");
        return 1;
    }
    child_pid = pid;

    int opened = 0;
    for (int i = 0; i < 40; i++) {
        if (health_ok()) {
            open_browser();
            opened = 1;
            break;
        }
        usleep(250000);
    }
    if (!opened) {
        alert("助手启动超时。可查看 ~/.wechat-assist/server.log");
        kill(child_pid, SIGTERM);
        return 1;
    }

    int status = 0;
    waitpid(child_pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
