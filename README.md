# audio-stream-google-home

Stream MP3 to a specific Google Home Device using Python

# Architecture Diagram

The architecture contains several parts like the ESP-32, the TFT and some components. The backend server is also a critical parts and it is what this repository is all about.

![](AudioBookArchitecture.png)


# Environment

```sh
uv init
``` 

# Network WSL

Running for dev in WSL requires redirecting for the Google Home device to talk to the dev machine and then inside WSL:

Get the IP of the dev machine using CMD and this command: 

```
ipconfig
```
Let's pretend the ip is `10.0.0.73`

Inside WSL to find the ip:
```
ip addr show eth0
```
Let's predend the ip is `172.19.71.162`


Then in Powershell admin:
```
netsh interface portproxy add v4tov4 listenaddress=10.0.0.73 listenport=8801 connectaddress=172.19.71.162 connectport=8801

New-NetFirewallRule -DisplayName "WSL FastAPI" -Direction Inbound -LocalPort 8801 -Protocol TCP -Action Allow
```

# Network Server
Make sure the IP and PORT on the machine are accessible

```sh
sudo ufw allow 8801/tcp
sudo ufw reload
```

# Testing

You can start the server using `make server` and then call it:

```
 curl -X POST http://10.0.0.73:8801/play \
     -H "Content-Type: application/json" \
     -d '{"track": "x.mp3"}'
```

# Service
```
sudo cp systemd/audio-book.service /etc/systemd/system/audio-book.service
sudo systemctl daemon-reload
sudo systemctl enable --now audio-book.service

sudo systemctl start audio-book.service
sudo systemctl stop audio-book.service
sudo systemctl restart audio-book.service
sudo journalctl -u audio-book -n 100 -f
```

# Example of HTTP Requests

```sh
curl -X POST http://10.0.0.181:8801/play \
     -H "Content-Type: application/json" \
     -d '{"track": "Adventure_05_Tom_Sawyer", "device": "Jacob"}'


curl -X POST http://localhost:8801/play \
-H "Content-Type: application/json" \
-d '{"track": "x", "device": "Jacob"}'
```

# Debug

Check if we can access the Google Home:

```sh
ping 10.0.0.88
nc -zv 10.0.0.88 8009
```