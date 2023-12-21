# ulotterybot

## Install
-  Clone this repo `git clone https://github.com/r3x5ur/ulotterybot.git`
1. Virtual env `python3 -m venv venv`
2. Activate venv:
    - Linux or MacOS `source venv/bin/activate`
    - Windows `venv\Scripts\activate`
3. Install dependencies `pip install -r requirements.txt`
4. Rename [.env.example](.env.example) to .env and Edit your ENV
5. Run server `python app.py`

## Install On Docker

-  Clone this repo `git clone https://github.com/r3x5ur/ulotterybot.git`
1. Edit the `environment` field of [docker-compose.yml](docker-compose.yml)
2. Run container `docker-compose up -d`