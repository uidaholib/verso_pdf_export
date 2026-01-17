## Setup

download .env file from SharePoint folder and drop into base repository (this is included in the .gitignore, so that information will not be committed)

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

mkdir A B C

**to generate full PDF files and metadata**

python script.py

**to only generate metadata**

python md_script.py

**to keep device from sleeping while running the tasks**

caffeinate python script.py

caffeinate python md_script.py
