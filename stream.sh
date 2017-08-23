#!/bin/sh
ffmpeg -re -loglevel panic -loop 1 -framerate 2 -i images/$1 -i /tmp/current.wav -c:a aac -s 2560x1440 -ab 128k -vcodec libx264 -pix_fmt yuv420p -maxrate 2048k -bufsize 2048k -framerate 30 -g 2 -strict experimental -shortest -f flv $2
#ffmpeg -re -loop 1 -framerate 2 -i images/$1 -i /tmp/current.wav -c:a aac -s 2560x1440 -ab 128k -vcodec libx264 -pix_fmt yuv420p -maxrate 2048k -bufsize 2048k -framerate 30 -g 2 -strict experimental -shortest -f flv $2
