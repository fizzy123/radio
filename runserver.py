# pragma pylint: disable=missing-docstring, invalid-name, superfluous-parens
import sys
import re
import random
import subprocess
import sqlite3
import argparse

from os import listdir
from os.path import isfile, join, realpath

import requests
import youtube_dl
from flask import Flask, render_template, request, jsonify, g, has_request_context
from flask_socketio import SocketIO

app = Flask(__name__, static_url_path='/static')
socketio = SocketIO(app)

config = {}
MESSAGES_LENGTH = 100

CUR_DIR = '/'.join(realpath(__file__).split('/')[0:-1])

def get_db():
    conn = sqlite3.connect('{}/radio.db'.format(CUR_DIR))
    conn.row_factory = sqlite3.Row
    if not has_request_context():
        return conn
    if not hasattr(g, 'db'):
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

@app.route("/", methods=['GET'])
def messages():
    return render_template('index.html', title=config['broadcast-title'], id=config['broadcast-title'].lower().replace(' ', '-'))

@app.route("/messages", methods=['GET'])
def index():
    conn = get_db()
    query = """SELECT message, username
               FROM messages
               ORDER BY created_at
            """
    messages = list(conn.cursor().execute(query))[-50:]
    return jsonify({'messages': [dict(zip(row.keys(), row)) for row in messages]})

@socketio.on('message_emit')
def message(data):
    message = data['message']
    username = data['username']
    socketio.emit('message_emit', {'message': message, 'username': username})
    commit_message(message, username)
    parse_message(message)
    return jsonify({'success': True})

@app.route("/done", methods=['POST'])
def done():
    play_song()
    return jsonify({'success': True})

def commit_message(message, username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""INSERT INTO messages (message, username) values(?, ?)""", (message, username))
    conn.commit()

def parse_message(message):
    if '++' in message[:2] and config['enable-upvotes']:
        upvote()
    elif '--' in message[:2] and config['enable-downvotes']:
        print('Downvoted!')
        downvote()
        skip = subprocess.Popen(['pkill', 'ffmpeg'], stdout=subprocess.PIPE)
        skip.wait()
    elif message[0:4] == '!add' and config['enable-adding']:
        print('Added!')
        url = message.split(' ')[1]
        if 'youtube.com' in url or 'youtu.be' in url or 'soundcloud.com' in url:
            response_text = "Added {} to the playlist!".format(message.split(' ')[1])
            commit_message(response_text, "RADIOBOT")
            socketio.emit('message_emit', {'message': response_text, 'username': 'RADIOBOT'})
            upvote(times=5, url=message.split(' ')[1])
        else:
            response_text = "{} is an invalid url!".format(message.split(' ')[1])
            commit_message(response_text, "RADIOBOT")
            socketio.emit('message_emit', {'message': response_text, 'username': 'RADIOBOT'})
    elif message[0:5] == '!help':
        response_text = config['description']
        commit_message(response_text, "RADIOBOT")
        socketio.emit('message_emit', {'message': response_text, 'username': 'RADIOBOT'})

def download(url):
    ydl_opts = {
        'quiet': True,
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '0'


        }],
        'outtmpl': '/tmp/staging.wav'
    }
    config['history'].append(url)
    if len(config['history']) > 5:
        config['history'] = config['history'][-5:]
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def run():
    query = """SELECT url
               FROM songs
               ORDER BY RANDOM()
               LIMIT 10
            """
    conn = get_db()
    candidates = [url for url in list(conn.cursor().execute(query)) if url['url'] not in config['history']]

    config['staging_url'] = candidates[0]['url']
    delete = subprocess.Popen(['rm', '-rf', '/tmp/staging.wav'], stdout=subprocess.PIPE)
    delete.wait()
    download(config['staging_url'])
    play_song()

def play_song():
    swap = subprocess.Popen(['mv', '/tmp/staging.wav', '/tmp/current.wav'], stdout=subprocess.PIPE)
    config['current_url'] = config['staging_url']
    swap.wait()
    if swap.returncode != 0:
        raise RuntimeError('Swap Failed')
    image = '{}/images/{}'.format(CUR_DIR, random.choice([f for f in listdir('{}/images'.format(CUR_DIR)) if isfile(join('{}/images'.format(CUR_DIR), f))]))
    info = get_info(config['current_url'])
    stream = subprocess.Popen(['{}/stream.sh'.format(CUR_DIR),
                               image,
                               info.encode('utf-8'),
                               '{}/{}'.format(config['rtmp-server'],
                                              config['broadcast-title'].lower().replace(' ', '-'))

                              ])
    response_text = "Coming up: <a href='{}'>{}</a>".format(config['current_url'], info)
    commit_message(response_text, "RADIOBOT")
    socketio.emit('message_emit', {'message': response_text, 'username': 'RADIOBOT'})

    query = """SELECT url
               FROM songs
               ORDER BY RANDOM()

               LIMIT 10
            """

    conn = get_db()
    candidates = [url for url in list(conn.cursor().execute(query)) if url['url'] not in config['history']]
    config['staging_url'] = candidates[0]['url']
    delete = subprocess.Popen(['rm', '-rf', '/tmp/staging.wav'], stdout=subprocess.PIPE)
    delete.wait()
    if delete.returncode != 0:
        raise RuntimeError('Delete Failed')
    download(config['staging_url'])

def get_info(url):
    if 'youtube' in url or 'youtu.be' in url:
        return get_youtube_info(url)
    elif 'soundcloud' in url:
        return get_soundcloud_info(url)
    else:
        return None

def get_youtube_info(url=None):
    if not url:
        url = config['current_url']

    if 'youtube' in url:
        video_id = re.search(r"\?v=([a-zA-z0-9\-]+)", url).group(1)
    elif 'youtu.be' in url:
        video_id = url.split('/')[-1]
# pylint: disable=line-too-long
    response = requests.get('https://www.googleapis.com/youtube/v3/videos?id={}&key={}&part=snippet'.format(video_id, config['youtube_api_key']))
    title = response.json()['items'][0]['snippet']['title']
    return title

def get_soundcloud_info(url=None):
    if not url:
        url = config['current_url']
    parts = url.replace('-', ' ').split('?')[0].split('/')
    return "{} - {}".format(parts[-2], parts[-1])

def init():
    # db structure is a little weird.
    # Rather than having a score explicitly, the score will be how many rows with that url exist.

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS songs")
    cur.execute("""CREATE TABLE songs (

                     id INTEGER PRIMARY KEY NOT NULL,
                     url TEXT NOT NULL
                   )
                """)
    cur.execute("DROP TABLE IF EXISTS messages")
    cur.execute("""CREATE TABLE messages (
                     id INTEGER PRIMARY KEY NOT NULL,
                     created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                     message TEXT NOT NULL,

                     username TEXT NOT NULL
                    )
                """)
    conn.commit()

def upvote(times=1, url=None):
    if not url:
        url = config['current_url']
    print("{} upvotes for {}".format(times, url))

    conn = get_db()
    cur = conn.cursor()
    cur.executemany("""INSERT INTO songs (url) values(?)""", [(url,)] * times)
    conn.commit()
    if config.get('broadcast-title'):
        dump(config['broadcast-title'].lower().replace(' ', '-'))

def downvote(times=1):
    print("{} downvotes for {}".format(times, config['current_url']))
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""DELETE FROM songs
                   WHERE id = (SELECT id
                               FROM songs
                               WHERE url=?
                               LIMIT ?)""", (config['current_url'], times,))
    conn.commit()
    dump(config['broadcast-title'].lower().replace(' ', '-'))

def dump(key):
    query = """SELECT url, count(*) as score
               FROM songs
               GROUP BY url
            """
    conn = get_db()
    rows = list(conn.cursor().execute(query))

    row_list = [dict(zip(row.keys(), row)) for row in rows]
    row_list = sorted(row_list, key=lambda row: row['score'])
    result_string = "Full song list for {}\n\nsong|score\n".format(key)
    for row in row_list:
        info = get_info(row['url'])
        result_string = result_string + info + '|' + str(row['score']) + '\n'
    result_string = result_string + "\n\n#readonly"
    requests.post('http://nobr.me/general/ram/', {'key': key, 'body': result_string})

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == 'init':
            init()
            sys.exit()

        elif sys.argv[1] == 'add':
            upvote(url=sys.argv[2])
            sys.exit()
        elif sys.argv[1] == 'dump':
            dump(sys.argv[2])
            sys.exit()
    parser = argparse.ArgumentParser(description='Host a radio website')
    parser.add_argument("--broadcast-title", help="Broadcast title",
                        default="Nobel Radio")
    parser.add_argument("--disable-upvotes", help="Disable Upvotes")
    parser.add_argument("--disable-downvotes", help="Disable Downvotes")
    parser.add_argument("--disable-adding", help="Disable Adding Songs")
    parser.add_argument("--description", help="Description")
    parser.add_argument("--rtmp-server", help="Description", default='10.180.184.1')
    args = parser.parse_args()
    if not args.description:
        args.description = ''

# pylint: disable=line-too-long
    args.description = "{}\n\n<a href='http://nobr.me/general/ram/?key={}'>Playlist</a>".format(args.description, args.broadcast_title.lower().replace(' ', '-'))
    if not args.disable_upvotes or \
       not args.disable_downvotes or \
       not args.disable_adding:
        args.description = args.description + "\n\nCOMMANDS:\n"

        if not args.disable_upvotes:
# pylint: disable=line-too-long
            args.description = args.description + "++ - Upvote current song. More Upvoted songs will play more often\n"
        if not args.disable_downvotes:
# pylint: disable=line-too-long
            args.description = args.description + "-- - Downvote current song. More Downvoted songs will play less often\n"
        if not args.disable_adding:
            args.description = args.description + "!add {url} - Add a song from a url. Officially only supports youtube and soundcloud at the moment.\n"
    config['broadcast-title'] = args.broadcast_title
    config['rtmp-server'] = args.rtmp_server
    config['enable-upvotes'] = not args.disable_upvotes
    config['enable-downvotes'] = not args.disable_downvotes
    config['enable-adding'] = not args.disable_adding
    config['youtube_api_key'] = 'AIzaSyDMxVYD6VEhw8clYtPKIRyRqnx4rec3cNk'
    config['description'] = args.description.strip()
    config['history'] = []
    run()
    socketio.run(app, port=3000, debug=True, host='0.0.0.0', use_reloader=False)
