#!/bin/sh
# https://stackoverflow.com/questions/43586435/ffmpeg-to-youtube-live
ffmpeg -re -loglevel quiet -loop 1 -i images/$1 -i /tmp/current.wav -c:a aac -s 1920x1080 -ab 128k -maxrate 2048k -bufsize 2048k -framerate 30 -strict experimental -shortest -f flv $2
