import SocketServer
import BaseHTTPServer
import SimpleHTTPServer
import os
import sys
import json
import httplib
import urllib
import hashlib
import threading
import random


class RequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

  # Handle incoming GET request
  def do_GET(self):
    sha256   = hashlib.sha256()
    filehash = self.path[1:]
    headers  = str(self.headers).split('\r\n')

  # Parse request headers
    for header in headers:
      if header.startswith('Range: bytes='):
        _range = header.split('=')[1]
        start  = _range.split('-')[0]
        end    = _range.split('-')[1]
        break

   # Find file requested by matching on filehash and send the
   # requested part of the file
    files = os.listdir('.')
    for file in files:
      with open(file, 'rb') as f:
        content = f.read()
        digest = hashlib.sha256(content).hexdigest()

        if digest == filehash:
          print 'File found, sending response...'
          range_header  = 'bytes=' + start + '-' + end + '/' + str(len(content))
          response_size = int(end) - int(start) + 1

          f.seek(int(start))
          data = f.read(response_size)

          self.send_response(206)
          self.send_header("Range", range_header)
          self.send_header("Content-length", response_size)
          self.send_header("Content-type", "application/octet-stream")
          self.end_headers()
          self.wfile.write(data)
          return
    # If the request is valid but all files have been iterated through,
    # the file can not be found (404)
    self.send_response(404)


class ThreadingSimpleServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    pass


# Checks for json files. If one is found, check if the output file
# belonging to it has been downloaded. Else download it.
def loop_download():
  blocksize = int(sys.argv[3])
  while 1:
    files = os.listdir('.')
    for file in files:

      if file.endswith('.json'):

        # Open json file
        with open(file, 'r') as f:
          config   = json.load(f)
          filename = config['filename']
          if not active_thread(filename):
            # If kaskasdes out file doesnt exist, create it
            if not os.path.exists(filename):
              with open(filename, 'wb') as f:
                f.seek(config['filesize']-1)
                f.write('\0')
            
            # Open output file
            with open(filename, 'r') as f:
              sha256 = hashlib.sha256()
              sha256.update(f.read())
              local_file_digest = sha256.hexdigest()
              # If file is already downloaded and correct, continue.
              # Else download what is missing
              if local_file_digest == config['filehash']:
                continue
              else:
                  download_thread = threading.Thread(target=download, name=filename, args=(config, blocksize))
                  download_thread.daemon = True
                  download_thread.start()


# If a thread with the given name is active return true, else return false
def active_thread(name):
  thread_list = threading.enumerate()
  for thread in thread_list:
    if thread.getName() == name:
      return 1
  return 0


# Downloads a file given by filename, with the blocksize blocksize
# and with the .json file config.
def download(config, blocksize):
  print '\n\nDownloading file: '
  print threading.current_thread().getName()
  print '\n'

  blockcount  = (config['filesize'] + (blocksize - 1)) / blocksize # rounding up

  with open(config['filename'], 'r+b') as rf:

    # Find all peers that have the file we want to download,
    # and set our own progress to 0.0
    peers = register_and_get_peers(config['filehash'], 0)

    # Match block of file with kaskade file per md5hash 
    # -- if there is a mismatch we need to download the correct block
    for blockindex in range(0, blockcount):
      rf.seek(blockindex * blocksize)

      bytedata = rf.read(blocksize)
      hashsum  = hashlib.md5(bytedata).hexdigest()
      blockhashsum = config['blockhashes'][str(blocksize)][blockindex]
      if hashsum != blockhashsum:

        random.shuffle(peers)

        for peer in peers:
          if not peer['feeder']:
            continue

          print 'Downloading...'
          bytedata = download_block(peer, config, blocksize, blockindex)
          hashsum = hashlib.md5(bytedata).hexdigest()

          if hashsum == blockhashsum:
            rf.seek(blockindex * blocksize)
            rf.write(bytedata)
            break

        if hashsum != blockhashsum:
          print 'Unable to download block ' + str(blockindex)

    # Validate that the file has been correctly downloaded
    rf.seek(0)
    sha256 = hashlib.sha256()
    sha256.update(rf.read())
    if sha256.hexdigest() != config['filehash']:
      print 'Download success, but file is incorrect'
      return

    print 'File ' + config['filename'] + ' downloaded correctly'
    # Set our progress for the file to 1.0
    register_and_get_peers(config['filehash'], 1)


# Send POST request to tracker. Tracker will return a list
# of peers that we can download from
def register_and_get_peers(filehash, progress):
  if progress:
    data = urllib.urlencode({'port': port, 'progress': '1.0'})
  else:
    data = urllib.urlencode({'port': port, 'progress': '0.0'})

  headers =   {'Content-Type': 'application/x-www-form-urlencoded',
         'Connection': 'close'}

  conn = httplib.HTTPConnection('datanet2015tracker.appspot.com')

  conn.request('POST', '/peers/' + filehash + '.json', data, headers)

  response = conn.getresponse()

  peers = response.read()

  conn.close()
  peers = json.loads(peers)
  return peers

# Download a block defined by blockindex, blocksize. 
# The block is a part of the output file for the config file.
# Peer is the ip to download the block from.
def download_block(peer, config, blocksize, blockindex):
  blockcount = (config['filesize'] + (blocksize - 1)) / blocksize # rounding up

  # Get all peer info
  ip = peer['ip']
  port = peer['port']
  feeder = peer['feeder']
  progress = peer['progress']
  updated = peer['updated']

  filehash = config['filehash']
  range_start = blocksize * blockindex

  # Specify the range of bytes we want to request, special case -> skriv noget her
  if blockindex == blockcount - 1:
    range_end = config['filesize'] - 1
  else:
    range_end = range_start + blocksize - 1


  # Create request and return data from response
  conn    = httplib.HTTPConnection(ip, port)
  headers = {
    'Connection': 'close',
    'Range':      'bytes=' + str(range_start) + '-' + str(range_end)
  }
  conn.request('GET', '/' + filehash, '', headers)

  response = conn.getresponse()
  data = response.read()

  conn.close()
  return data


if __name__ == '__main__':

  os.chdir(sys.argv[1])
  port = int(sys.argv[2])

  server = ThreadingSimpleServer(('', port), RequestHandler)

  download_loop_thread = threading.Thread(target=loop_download, name='Download loop')
  download_loop_thread.daemon = True
  download_loop_thread.start()
  try:

      while 1:
          print 'Listening...'
          print 'Amount of threads active: '
          print threading.enumerate()
          server.handle_request()
  except KeyboardInterrupt:
      print "Finished"
