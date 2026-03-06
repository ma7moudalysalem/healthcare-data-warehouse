
--- Load Patients From Stage DB

INSERT INTO HealthcareDB.dbo.patients
(
patient_id,
name,
Birth_date,
gender,
race,
state,
insurance_type
    
)

SELECT
Id,
concat([First],' ',middle+' ',[last]),
BIRTHDATE,
GENDER,
RACE,
STATE,

Case 
     when HEALTHCARE_COVERAGE = 0 Then 'No Insurance'
     when HEALTHCARE_COVERAGE < 20000 Then 'Basic'
     when HEALTHCARE_COVERAGE < 100000 Then 'Standard'
     Else 'Premium' 
END

FROM STG_HealthcareDB.dbo.patients ;


Select* from HealthcareDB.dbo.patients





-------------------------------------------


------ load Providers from Stage DB


INSERT INTO HealthcareDB.dbo.providers
(
    provider_id,
    name,
    specialty,
    organization,
    city

    )

SELECT
id,
NAME,
SPECIALITY,
ORGANIZATION,
CITY
   
FROM STG_HealthcareDB.dbo.providers


Select * from HealthcareDB.dbo.providers






---------------------------------------------------------------------

---- Load Encounters from Stage 


INSERT INTO HealthcareDB.dbo.encounters
(
    encounter_id,
    patient_id,
    provider_id,
    encounter_type,
    start_date,
    end_date,
    total_cost
)

SELECT
Id,
PATIENT,
PROVIDER,
ENCOUNTERCLASS,
START,
STOP,
TOTAL_CLAIM_COST
    
FROM STG_HealthcareDB.dbo.encounters s;


Select* from HealthcareDB.dbo.encounters





--------------------------------------------------------

------ Load Conditions from Stage


INSERT INTO HealthcareDB.dbo.conditions
(
 
    patient_id ,
    encounter_id,
    icd10_code,
    description,
    onset_date,
    resolved_date
)

SELECT
PATIENT,
ENCOUNTER,
CODE,
DESCRIPTION,
START,
STOP

  
FROM STG_HealthcareDB.dbo.conditions s;


select* from HealthcareDB.dbo.conditions





-----------------------------------------------------------

----- Load Medications from Stage

INSERT INTO HealthcareDB.dbo.medications
(
    patient_id ,
    encounter_id ,
    drug_code ,
    description ,
    start_date ,
    stop_date ,
    cost
)

SELECT
PATIENT,
ENCOUNTER,
CODE,
DESCRIPTION,
START,
STOP,
TOTALCOST
   

FROM STG_HealthcareDB.dbo.medications s;


Select* from HealthcareDB.dbo.medications




-------------------------------------------------------------------------

--- Load Claims from Stage 

INSERT INTO HealthcareDB.dbo.claims
(
 claim_id,
    patient_id,
    encounter_id ,
    payer_name,
    amount_billed,
    amount_paid,
    status
   
)

SELECT
claim_id,
patient_id,
encounter_id,
payer_name,
amount_billed,
amount_paid,
status
    
FROM STG_HealthcareDB.dbo.claims_py;


Select* from HealthcareDB.dbo.claims



----------------------------------------------------------

--- Load Vital_signs from Stage 


INSERT INTO HealthcareDB.dbo.Vital_Signs
(
    vital_id ,
    patient_id ,
    heart_rate ,
    systolic_bp ,
    diastolic_bp ,
    temp,
    spo2 ,
    [timestamp]

)

SELECT

device_id,
patient_id,
heart_rate,
systolic_bp,
diastolic_bp,
temperature,
spo2,
timestamp

FROM STG_HealthcareDB.dbo.vital_signs_py s;


Select* from HealthcareDB.dbo.Vital_Signs

















