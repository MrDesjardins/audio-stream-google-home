.PHONY: server 

server: 
	uv run ./src/audio-stream-google-home/main.py --host 0.0.0.0 --port 8801 --reload

