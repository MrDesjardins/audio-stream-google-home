# audio-stream-google-home

Stream MP3 to a specific Google Home Device using Python

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