.PHONY: server 

server: 
	uv run ./src/audio-stream-google-home/main.py --reload

