#! /usr/bin/env python3

# Install the required Python modules
# pip install pulsectl pydub

import dbus
import os
import sys
import time
import pprint
import pulsectl
import re
import requests
import subprocess
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from pydub import AudioSegment
from multiprocessing import Process

pre_subprocess = None
r = None
pre_album = ""
pre_artist = ""
pre_title = ""
pre_art_url = ""
pre_track_number = ""
pre_file_input = ""
pre_file_cover = ""
file_cover = ""
download_path = ""
advertisement_detected = False
spotify_sink_index = -1


def get_spotify_sink_index():
    with pulsectl.Pulse('spotify') as pulse:
        for sink in pulse.sink_input_list():
            # print("sink.name:" + sink.name)
            # print("sink.corked:" + str(sink.corked))
            if (sink.name == "Spotify") and (sink.corked == False):
                return sink.index

    return -1


def create_directory(path_album):
    # print("path_album: " + path_album)
    # re.sub("[^a-zA-Z]+", "", path_album) 
    re.sub("/", "-", path_album)
    # print("path_album: " + path_album)

    try:
        os.makedirs(path_album, exist_ok=True)
    except OSError:
        print("Creation of the directory %s failed, use /tmp" % path_album)
        return "/tmp"

    return path_album


def get_download_path():
    if sys.platform == "win32":
        command = r'reg query "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v "Downloads"'
        result = subprocess.run(command, stdout=subprocess.PIPE, text = True)
        download_path = result.stdout.splitlines()[2].split()[2]
    else:
        download_path = subprocess.check_output(['xdg-user-dir', 'DOWNLOAD'], text = True).rstrip('\n')

    if download_path == "":
        download_path = os.path.expanduser("~/Downloads")

    download_path = os.path.join(download_path, 'spotifyripper')
    print("download_path =  %s" % download_path)
    return download_path


def download_cover(art_url, file_cover):
    global r

    # print("file_cover: " + file_cover)
    # print("art_url: " + art_url)
    if (art_url != ""):
        # if art_url != pre_art_url:
        r = requests.get(art_url, allow_redirects=True)
    if r != None:
        open(file_cover, 'wb').write(r.content)


def convert_to_mp3(a_file_input, a_file_cover, a_album, a_artist, a_title, a_track_number):
    #print("convert_to_mp3: start converting " + a_file_input)
    # Use internal filename to Protect from successive conversion
    a_temp_file_input = a_file_input.replace(".wav", "-tmp.wav")
    a_file_output = a_file_input.replace(".wav", ".mp3")
    os.rename(a_file_input, a_temp_file_input)

    sound = AudioSegment.from_wav(a_temp_file_input)
    sound.export(a_file_output, format="mp3", bitrate="320k", cover=a_file_cover, tags={
            "album": a_album,
            "artist": a_artist,
            "title": a_title,
            "track": int(a_track_number)
        }
    )

    a_file_output_size = os.stat(a_file_output).st_size
    if a_file_output_size < 1048576:
        print('\033[33m' + "Warning: small file " + a_file_output + " \033[0m\n")

    if a_file_output_size > 25485760:
        print('\033[33m' + "Warning: large file " + a_file_output + " \033[0m\n")

    # print("DELETE " + a_file_cover)
    os.remove(a_file_cover)
    # print("DELETE " + a_file_input)
    os.remove(a_temp_file_input)
    #print("convert_to_mp3: done converting " + a_file_input)


def spotify_handler(*args):
    global pre_album
    global pre_artist
    global pre_title
    global pre_subprocess
    global pre_art_url
    global pre_track_number
    global pre_file_input
    global pre_file_cover
    global download_path
    global r
    global advertisement_detected
    global spotify_sink_index

    metadata = args[1]["Metadata"]
    # debug
    #pprint.pprint(metadata)

    artist = metadata["xesam:artist"][0]
    #print("Artist: " + artist)
    albumArtist = metadata["xesam:albumArtist"][0]
    #print("AArtist " + albumArtist)
    title = metadata["xesam:title"]
    album = metadata["xesam:album"]
    track_number = metadata["xesam:trackNumber"]
    art_url = metadata["mpris:artUrl"]
    disc_number = int(metadata["xesam:discNumber"])
    
    # if albumArtist != "":
    #     artist = albumArtist
    
    if albumArtist == "":
        albumArtist = artist

    if title != "":
        title = title.replace("/", "-")
        
    # workaround for art URL
    art_url = art_url.replace("open.spotify.com", "i.scdn.co")

    if title != pre_title:
        print("Artist: " + artist)
        print("AlbumArtist: " + albumArtist)
        print("Album: " + album)
        print("Title: " + str(track_number) + " - " + title)
        # print("Cover: " + art_url)
        # print("Track: " + str(track_number))
        print()


        # create dir
        path_base = os.path.expanduser(download_path)
        if disc_number > 1:
            disc_number_str = str(disc_number) + " "
        else:
            disc_number_str = ""
        path_album = create_directory(path_base + "/" + albumArtist + "/" + disc_number_str + album)
        # print("path_album: " + path_album)

        # record stream
        if pre_subprocess != None:
            pre_subprocess.terminate()
        file_input = path_album + "/" + str(track_number) + " - " + artist + " - " + title + ".wav"

        if spotify_sink_index == -1:
            spotify_sink_index = get_spotify_sink_index()
            print("spotify_sink_index: " + str(spotify_sink_index))
            # If Spotify not found, do nothing
            if spotify_sink_index == -1:
                print("the Spotify client is not found.")
                print("It has to be registered with the audio server by playing a sound.")
                return


        if (artist != "") or (album != ""):
            # parec starts too soon after the advertisement bits.
            # Add 1s delay in order to skip the end of the advertisement.
            if advertisement_detected == True:
                time.sleep(1)
            pre_subprocess = subprocess.Popen(["parec",  "--monitor-stream=" + str(spotify_sink_index), "--file-format=wav", file_input])
            advertisement_detected = False

        # convert previous file
        if os.path.isfile(pre_file_input):
            Process(target=convert_to_mp3, args=(pre_file_input, pre_file_cover, pre_album, pre_artist, pre_title, pre_track_number)).start()

        # download cover
        file_cover = file_input.replace(".wav", ".jpg")
        download_cover(art_url, file_cover)
        if art_url != "":
            pre_art_url = art_url
        if file_cover != "":
            pre_file_cover = file_cover

        pre_file_input = file_input

    if album != "":
        pre_album = album
    if artist != "":
        pre_artist = artist
    if title != "":
        pre_title = title
    if track_number != "":        
        pre_track_number = track_number
    if (artist == "") and (album == ""):
        advertisement_detected = True


download_path = get_download_path()
spotify_sink_index = get_spotify_sink_index()

DBusGMainLoop(set_as_default=True)
session_bus = dbus.SessionBus()
session_bus.add_signal_receiver(spotify_handler, 'PropertiesChanged', None, 'org.mpris.MediaPlayer2.spotify',  '/org/mpris/MediaPlayer2')

loop = GLib.MainLoop()
loop.run()
