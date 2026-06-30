## Setup

download .env file from SharePoint folder and drop into base repository (this is included in the .gitignore, so that information will not be committed)

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

mkdir A B C

**test to make sure API key is still valid**

python debug.py

**generate full PDF files and metadata**

python script.py full

**generate only ETD PDF files and metadata**

python script.py ETD

**generate everything but ETD PDF files and metadata**

python script.py sansETD

**to only generate metadata**

python md_script.py

**to keep device from sleeping while running the tasks**

caffeinate -di python script.py full

caffeinate -di python script.py ETD

caffeinate -di python script.py sansETD

caffeinate -di python md_script.py
