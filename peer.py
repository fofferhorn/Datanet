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

  #handle incoming GET request
  def do_GET(self):
    sha256   = hashlib.sha256()
    filehash = self.path[1:]
    headers  = str(self.headers).split('\r\n')

  #parse request headers
    for header in headers:
      if header.startswith('Range: bytes='):
        _range = header.split('=')[1]
        start  = _range.split('-')[0]
        end    = _range.split('-')[1]
        break

   #find file requested by matching on filehash and send the requested part of the file
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
    #if the request is valid but all files have been iterated through, the file can not be found (404)
    self.send_response(404)


class ThreadingSimpleServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    pass

def download_block(peer, config, blocksize, blockindex):
  blockcount = (config['filesize'] + (blocksize - 1)) / blocksize # rounding up

  #get all peer info
  ip = peer['ip']
  port = peer['port']
  feeder = peer['feeder']
  progress = peer['progress']
  updated = peer['updated']

  filehash = config['filehash']
  range_start = blocksize * blockindex

#specify the range of bytes we want to request, special case -> skriv noget her
  if blockindex == blockcount - 1:
    range_end = config['filesize'] - 1
  else:
    range_end = range_start + blocksize - 1


#create request and return data from response
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

#loop
def loop_download():
  while 1:
    download()

def download():
  blocksize = 1024
  with open('ddo_dns.pdf.json', 'r') as f:
    config = json.load(f)

#if kaskasdes out file doesnt exist, create it
  if not os.path.exists(config['filename']):
    with open(config['filename'], 'wb') as f:
      f.seek(config['filesize']-1)
      f.write('\0')

  blockcount  = (config['filesize'] + (blocksize - 1)) / blocksize # rounding up
  sha256      = hashlib.sha256()
  sha256check = hashlib.sha256()

  with open(config['filename'], 'r+b') as rf:

 #check if file has already been downloaded
    sha256check.update(rf.read())
    local_file_digest = sha256check.hexdigest()
    if local_file_digest == config['filehash']:
      return

 #find all peers that have the file we want to download
    peers = register_and_get_peers(config['filehash'], 0)

  #match block of file with kaskade file per md5hash -- if there is a mismatch we need to download to correct block
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

          print 'Downloading file from ' + peer['ip']
          bytedata = download_block(peer, config, blocksize, blockindex)
          hashsum = hashlib.md5(bytedata).hexdigest()

          if hashsum == blockhashsum:
            print 'Writing block from ' + peer['ip']
            rf.seek(blockindex * blocksize)
            rf.write(bytedata)
            break

        if hashsum != blockhashsum:
          print 'Unable to download block ' + str(blockindex)


    #validate that the file has been correctly downloaded
    rf.seek(0)
    sha256.update(rf.read())
    print 'Hash for downloaded file: ' + str(sha256.hexdigest())
    if sha256.hexdigest() != config['filehash']:
      print 'Download success, but file is incorrect'
      return

    print 'File ' + config['filename'] + ' downloaded correctly'
    register_and_get_peers(config['filehash'], 1)



#send POST request to tracker. Tracker will return a list of peers that we can download from
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

if __name__ == '__main__':

  os.chdir(sys.argv[1])
  port = int(sys.argv[2])

  server = ThreadingSimpleServer(('', port), RequestHandler)

  download_thread = threading.Thread(target=loop_download)
  download_thread.daemon = True
  download_thread.start()
  try:

      while 1:
          print 'Listening...'
          server.handle_request()
  except KeyboardInterrupt:
      print "Finished"
