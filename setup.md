## Setup

download .env file from SharePoint folder and drop into base repository (this is included in the .gitignore, so that information will not be committed)

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

mkdir A B C

**Generate New assetsWITHPDFs Report**

First:

https://alliance-uidaho-researchmanagement.esploro.exlibrisgroup.com/mng/login?auth=SAML

Then:

https://analytics12-na.esploro.exlibrisgroup.com/analytics/saw.dll?Answers&path=%2Fshared%2FUniversity%20of%20Idaho%2FReports%2FnormTesting%2FassetsWithPDFs

- Drop in repo root

- Preserve name if only exporting metadata. Rename the report to assetsWithPDFs_previous.csv if generating metadata and new assets

- The script will contrast the newest report with the last and only export files and metadata for the new items. To generate the full database, remove the _previous version from the root

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
