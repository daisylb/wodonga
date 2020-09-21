#!/bin/zsh
sudo launchctl bootout system /Library/LaunchDaemons/au.net.leigh.wodonga.*.plist
launchctl bootout gui/$(id -ur) ~/Library/LaunchAgents/au.net.leigh.wodonga.server.plist
sudo rm /Library/LaunchDaemons/au.net.leigh.wodonga.*.plist ~/Library/LaunchAgents/au.net.leigh.wodonga.server.plist