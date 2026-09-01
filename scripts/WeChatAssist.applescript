on appPath()
	set p to POSIX path of (path to me)
	if p ends with "/applet" then
		set p to do shell script "/usr/bin/dirname " & quoted form of p
		set p to do shell script "/usr/bin/dirname " & quoted form of p
		set p to do shell script "/usr/bin/dirname " & quoted form of p
	end if
	if p does not end with "/" then set p to p & "/"
	return p
end appPath

on launchHelper()
	set bundle to my appPath()
	set launchSh to bundle & "Contents/Resources/launch.sh"
	set rootFile to bundle & "Contents/Resources/project-root"
	set cmd to "export WECHAT_ASSIST_DETACH=1; export WECHAT_ASSIST_ROOT=\"$(/usr/bin/tr -d '\\n' < " & quoted form of rootFile & ")\"; /bin/bash " & quoted form of launchSh
	do shell script cmd
end launchHelper

on run
	try
		my launchHelper()
	on error errMsg
		display dialog errMsg buttons {"好"} default button 1 with title "微信回复助手" with icon stop
	end try
end run

on reopen
	try
		do shell script "/usr/bin/open http://127.0.0.1:8765"
	end try
end reopen

on quit
	try
		do shell script "pid=$(/bin/cat \"$HOME/.wechat-assist/server.pid\" 2>/dev/null); if [ -n \"$pid\" ]; then kill \"$pid\" 2>/dev/null; fi; rm -f \"$HOME/.wechat-assist/server.pid\""
	end try
	continue quit
end quit
