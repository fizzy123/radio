#!/bin/sh
# https://stackoverflow.com/questions/43586435/ffmpeg-to-youtube-live
ffmpeg -loop 1 -re -i images/$1 -i /tmp/current.wav -vcodec libx264 -vprofile baseline -vf drawtext="fontfile=/path/to/font.ttf: text='$2': fontcolor=white: fontsize=18: box=1: boxcolor=black@0.5: boxborderw=5: x=(w-text_w)/2: y=(h-text_h)/2" -c:a aac -s 1920x1080  -framerate 2 -strict experimental -shortest -preset ultrafast -f flv rtmp://$3/stream
