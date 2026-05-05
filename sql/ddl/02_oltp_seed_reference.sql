/* =========================================================================
   02_oltp_seed_reference.sql
   Idempotent seed for reference tables (hospitals, codes, payers).

   Run with:
       sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -d healthcare_oltp \
              -i sql/ddl/02_oltp_seed_reference.sql

   Re-running this script is safe; existing rows are left untouched.
   ========================================================================= */

USE healthcare_oltp;
GO

/* ---------- Hospital network ------------------------------------------ */
;WITH src(hospital_code, hospital_name, city, governorate, bed_count, is_clinic) AS (
    SELECT * FROM (VALUES
        ('HSP-CAI-01', N'Cairo Central Hospital',        N'Cairo',      N'Cairo',      320, 0),
        ('HSP-CAI-02', N'Nile Heart Institute',          N'Cairo',      N'Cairo',      180, 0),
        ('HSP-GIZ-01', N'Giza Specialty Hospital',       N'Giza',       N'Giza',       240, 0),
        ('HSP-ALX-01', N'Alexandria Bayside Medical',    N'Alexandria', N'Alexandria', 280, 0),
        ('HSP-MNF-01', N'Menoufia Regional Medical',     N'Shebin El Kom', N'Menoufia', 150, 0),
        ('CLN-CAI-01', N'Cairo Family Clinic 1',         N'Cairo',      N'Cairo',      0,   1),
        ('CLN-CAI-02', N'Cairo Family Clinic 2',         N'Cairo',      N'Cairo',      0,   1),
        ('CLN-GIZ-03', N'Giza Family Clinic 3',          N'Giza',       N'Giza',       0,   1),
        ('CLN-GIZ-04', N'Giza Family Clinic 4',          N'Giza',       N'Giza',       0,   1),
        ('CLN-ALX-05', N'Alexandria Family Clinic 5',    N'Alexandria', N'Alexandria', 0,   1),
        ('CLN-ALX-06', N'Alexandria Family Clinic 6',    N'Alexandria', N'Alexandria', 0,   1),
        ('CLN-MNF-07', N'Menoufia Family Clinic 7',      N'Shebin El Kom', N'Menoufia', 0,   1),
        ('CLN-SHA-08', N'Sharqia Family Clinic 8',       N'Zagazig',    N'Sharqia',    0,   1),
        ('CLN-DAK-09', N'Dakahlia Family Clinic 9',      N'Mansoura',   N'Dakahlia',   0,   1),
        ('CLN-QAL-10', N'Qalyubia Family Clinic 10',     N'Banha',      N'Qalyubia',   0,   1),
        ('CLN-GHA-11', N'Gharbia Family Clinic 11',      N'Tanta',      N'Gharbia',    0,   1),
        ('CLN-BEH-12', N'Beheira Family Clinic 12',      N'Damanhur',   N'Beheira',    0,   1),
        ('CLN-ASW-13', N'Aswan Family Clinic 13',        N'Aswan',      N'Aswan',      0,   1),
        ('CLN-LUX-14', N'Luxor Family Clinic 14',        N'Luxor',      N'Luxor',      0,   1),
        ('CLN-SUE-15', N'Suez Family Clinic 15',         N'Suez',       N'Suez',       0,   1),
        ('CLN-FAY-16', N'Fayoum Family Clinic 16',       N'Fayoum',     N'Fayoum',     0,   1),
        ('CLN-MIN-17', N'Minya Family Clinic 17',        N'Minya',      N'Minya',      0,   1),
        ('CLN-BNS-18', N'Beni Suef Family Clinic 18',    N'Beni Suef',  N'Beni Suef',  0,   1),
        ('CLN-ASY-19', N'Asyut Family Clinic 19',        N'Asyut',      N'Asyut',      0,   1),
        ('CLN-SOH-20', N'Sohag Family Clinic 20',        N'Sohag',      N'Sohag',      0,   1)
    ) AS v(hospital_code, hospital_name, city, governorate, bed_count, is_clinic)
)
MERGE ref.hospital AS tgt
USING src
   ON tgt.hospital_code = src.hospital_code
WHEN NOT MATCHED THEN
    INSERT (hospital_code, hospital_name, city, governorate, bed_count, is_clinic)
    VALUES (src.hospital_code, src.hospital_name, src.city, src.governorate, src.bed_count, src.is_clinic);
GO

/* ---------- Payers ----------------------------------------------------- */
;WITH src(payer_name, is_government) AS (
    SELECT * FROM (VALUES
        (N'Misr Insurance',      0),
        (N'Allianz Egypt',       0),
        (N'AXA Egypt',           0),
        (N'Bupa Global',         0),
        (N'MetLife Egypt',       0),
        (N'Self-Pay',            0),
        (N'Health Insurance Org. (HIO)', 1)
    ) AS v(payer_name, is_government)
)
MERGE ref.payer AS tgt
USING src
   ON tgt.payer_name = src.payer_name
WHEN NOT MATCHED THEN
    INSERT (payer_name, is_government)
    VALUES (src.payer_name, src.is_government);
GO

/* ---------- ICD-10 (small representative subset) ----------------------- */
;WITH src(icd10_code, description, chapter) AS (
    SELECT * FROM (VALUES
        ('I10',     N'Essential (primary) hypertension',                                 N'Diseases of the circulatory system'),
        ('E11.9',   N'Type 2 diabetes mellitus without complications',                   N'Endocrine, nutritional and metabolic'),
        ('J45.909', N'Unspecified asthma, uncomplicated',                                N'Diseases of the respiratory system'),
        ('N39.0',   N'Urinary tract infection, site not specified',                      N'Diseases of the genitourinary system'),
        ('M54.5',   N'Low back pain',                                                    N'Diseases of the musculoskeletal system'),
        ('R51',     N'Headache',                                                         N'Symptoms and signs'),
        ('J18.9',   N'Pneumonia, unspecified organism',                                  N'Diseases of the respiratory system'),
        ('K21.9',   N'Gastro-esophageal reflux disease without esophagitis',             N'Diseases of the digestive system'),
        ('F32.9',   N'Major depressive disorder, single episode, unspecified',           N'Mental and behavioural disorders'),
        ('E78.5',   N'Hyperlipidemia, unspecified',                                      N'Endocrine, nutritional and metabolic'),
        ('I25.10',  N'Atherosclerotic heart disease of native coronary artery',          N'Diseases of the circulatory system'),
        ('N18.3',   N'Chronic kidney disease, stage 3',                                  N'Diseases of the genitourinary system'),
        ('G43.909', N'Migraine, unspecified, not intractable, w/o status migrainosus',   N'Diseases of the nervous system'),
        ('R07.9',   N'Chest pain, unspecified',                                          N'Symptoms and signs'),
        ('S52.501A',N'Unspecified fracture of the lower end of right radius, initial',   N'Injury, poisoning')
    ) AS v(icd10_code, description, chapter)
)
MERGE ref.icd10 AS tgt
USING src
   ON tgt.icd10_code = src.icd10_code
WHEN NOT MATCHED THEN
    INSERT (icd10_code, description, chapter)
    VALUES (src.icd10_code, src.description, src.chapter);
GO

/* ---------- CPT -------------------------------------------------------- */
;WITH src(cpt_code, description, base_charge_usd) AS (
    SELECT * FROM (VALUES
        ('99213', N'Office visit, established patient, level 3',  95.00),
        ('99214', N'Office visit, established patient, level 4',  145.00),
        ('99221', N'Initial hospital care, level 1',              210.00),
        ('99284', N'Emergency dept visit, level 4',               320.00),
        ('80053', N'Comprehensive metabolic panel',               45.00),
        ('85025', N'Complete blood count with differential',      28.00),
        ('71046', N'Chest X-ray, 2 views',                        110.00),
        ('93000', N'Electrocardiogram, complete',                 85.00),
        ('70551', N'MRI brain without contrast',                  825.00),
        ('36415', N'Routine venipuncture',                        12.00)
    ) AS v(cpt_code, description, base_charge_usd)
)
MERGE ref.cpt AS tgt
USING src
   ON tgt.cpt_code = src.cpt_code
WHEN NOT MATCHED THEN
    INSERT (cpt_code, description, base_charge_usd)
    VALUES (src.cpt_code, src.description, src.base_charge_usd);
GO

/* ---------- RxNorm ---------------------------------------------------- */
;WITH src(rxnorm_code, description) AS (
    SELECT * FROM (VALUES
        ('314076', N'Lisinopril 10 MG Oral Tablet'),
        ('860975', N'Metformin hydrochloride 500 MG Oral Tablet'),
        ('197361', N'Albuterol 0.09 MG/ACTUAT Metered Dose Inhaler'),
        ('197517', N'Amoxicillin 500 MG Oral Capsule'),
        ('197805', N'Atorvastatin 20 MG Oral Tablet'),
        ('310965', N'Ibuprofen 400 MG Oral Tablet'),
        ('198440', N'Acetaminophen 500 MG Oral Tablet'),
        ('314231', N'Omeprazole 20 MG Oral Capsule'),
        ('313782', N'Sertraline 50 MG Oral Tablet'),
        ('866924', N'Hydrochlorothiazide 25 MG Oral Tablet')
    ) AS v(rxnorm_code, description)
)
MERGE ref.rxnorm AS tgt
USING src
   ON tgt.rxnorm_code = src.rxnorm_code
WHEN NOT MATCHED THEN
    INSERT (rxnorm_code, description)
    VALUES (src.rxnorm_code, src.description);
GO

PRINT 'Reference data seeded.';
GO
