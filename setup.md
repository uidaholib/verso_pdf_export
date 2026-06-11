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

**environment variables for abstract harvesting**

add these to your `.env` file (alongside existing VERSO_API_KEY):

```
OPENALEX_API_KEY=your-key-here    # recommended, free at openalex.org; unauthenticated requests work but share a rate-limit pool
S2_API_KEY=                       # optional, gives guaranteed individual rate allocation for Semantic Scholar
```

**to enrich metadata with abstracts from a prior run**

python abstract_script.py --metadata C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json

use `--debug` to limit to 5 records for testing:

python abstract_script.py --metadata C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json --debug

**to import pre-harvested abstracts from a Universo BSON export**

python import_abstracts.py --bson unique_documents.bson --metadata C/YYYY-MM-DD_HH-MM-SS/asset_metadata.json

**to enrich abstracts inline during a regular export**

python script.py --enrich-abstracts

python md_script.py --enrich-abstracts
