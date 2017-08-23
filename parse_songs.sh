while read songs
do
  python radio.py add $songs
done < songs
