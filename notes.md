## Notes

Pending items:

### Base Report

It's saved as a report called "assetsWithPDFs" and is human-accessible from analytics -> Shared Folders/University of Idaho/Reports/normTesting/assetsWithPDFs.Eventually, we can have the python script you run automatically pull the report (as xml) using an alma analytics api key and making a get request to:

https://analytics12-na.esploro.exlibrisgroup.com/analytics/saw.dll?Go&Path=%2fshared%2fUniversity%20of%20Idaho%2fReports%2fnormTesting%2fassetsWithPDFs&Options=rmf

If we want to get really fancy and reproducible here's the SQL:

SELECT
   0 s_0,
   "Esploro Research Assets"."Asset Dates"."Asset Published Year" s_1,
   "Esploro Research Assets"."Asset Details"."Asset Type" s_2,
   "Esploro Research Assets"."Asset Details"."Has Files" s_3,
   "Esploro Research Assets"."Asset Details"."Title" s_4,
   "Esploro Research Assets"."Asset Identifiers"."Asset Id" s_5,
   "Esploro Research Assets"."Asset Usage"."Number of File Views / Downloads" s_6,
   "Esploro Research Assets"."Asset Usage"."Number of Record Views" s_7,
   "Esploro Research Assets"."File Details"."File Extension" s_8
FROM "Esploro Research Assets"
WHERE
(("Asset Details"."Has Files" = 'Yes') AND ("File Details"."File Extension" = 'pdf'))
ORDER BY 6 ASC NULLS FIRST, 3 ASC NULLS FIRST, 4 ASC NULLS FIRST, 5 ASC NULLS FIRST, 9 ASC NULLS FIRST, 2 ASC NULLS FIRST, 7 ASC NULLS FIRST, 8 ASC NULLS FIRST
FETCH FIRST 10000001 ROWS ONLY

## Next Steps

- See if you can incorporate updating reports into the script function using the API key so these are not distinct workflows.