------ 1- REMOVE DUPLICATES

select * from patients

WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY Id
               ORDER BY Id
           ) AS rn
    FROM patients
)

DELETE FROM CTE
WHERE rn > 1;


--- Check duplicates
SELECT
id,
COUNT(*) as duplicates

FROM patients

GROUP BY id

HAVING COUNT(*) > 1;



--------------------------------------------

-- encounters 

select * from encounters

WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY id
               ORDER BY id
           ) AS rn
    FROM encounters
)

DELETE FROM CTE
WHERE rn > 1;

--- check duplicates

SELECT id, COUNT(*)
FROM encounters
GROUP BY id
HAVING COUNT(*) > 1;

-----------------------------------



select * from medications

WITH CTE AS
(
    SELECT *,
           ROW_NUMBER() OVER (
                PARTITION BY
                    patient,
                    encounter,
                    code,
                    start
                ORDER BY patient
           ) AS rn
    FROM medications
)

DELETE FROM CTE
WHERE rn > 1;




------------------------------------------

Select * from providers

WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY id
               ORDER BY id
           ) AS rn
    FROM providers
)

DELETE FROM CTE
WHERE rn > 1;


--------------------------------------------
 
select * from conditions

WITH CTE AS
(
    SELECT *,
           ROW_NUMBER() OVER (
                PARTITION BY
                    patient,
                    encounter,
                    code,
                    start
                ORDER BY patient
           ) AS rn
    FROM conditions
)

DELETE FROM CTE
WHERE rn > 1;



-----------------------------------------------

Select * from claims_py

WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY claim_id
               ORDER BY claim_id
           ) AS rn
    FROM claims_py
)

DELETE FROM CTE
WHERE rn > 1;



-----------------------------------------

Select * from vital_signs_py

WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY device_id
               ORDER BY device_id
           ) AS rn
    FROM vital_signs_py
)

DELETE FROM CTE
WHERE rn > 1;


---------------------------------------------------------------------------------------------

------- 2- Handle Nulls

select * from conditions

UPDATE conditions
SET STOP = start
WHERE stop IS NULL;

Alter Table conditions
ADD [Status] varchar(50)

Update conditions
Set [Status] = 
Case  
      When STOP = START 
      Then 'Chronic Condition'
      Else 'Normal Condition'
End


-- who has a chronic condition we set the Start_date = Stop_date
-- and create [status] column to state the chronic condition 


-- 2.1 Fixing null costs for  Medication

 Select * from medications

UPDATE medications
SET TOTALCOST = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY TOTALCOST)
    OVER()
)
WHERE TOTALCOST IS NULL;

UPDATE medications
SET BASE_COST = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY BASE_COST)
    OVER()
)
WHERE BASE_COST IS NULL;



---- 2.1 Fixing null costs in Ecounters

Select * from encounters

UPDATE encounters
SET BASE_ENCOUNTER_COST = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY BASE_ENCOUNTER_COST)
    OVER()
)
WHERE BASE_ENCOUNTER_COST IS NULL;

UPDATE encounters
SET TOTAL_CLAIM_COST = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY TOTAL_CLAIM_COST)
    OVER()
)
WHERE TOTAL_CLAIM_COST IS NULL;


----- 2.3 Fixing null costs in Claims

Select * from claims_py

UPDATE claims_py
SET amount_billed = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY amount_billed)
    OVER()
)
WHERE amount_billed IS NULL;

UPDATE claims_py
SET amount_paid = (
    SELECT PERCENTILE_CONT(0.5) 
    WITHIN GROUP (ORDER BY amount_paid)
    OVER()
)
WHERE amount_paid IS NULL;





----------------------------------------- 3- Standarize Date Format 

--- encounters 
select * from encounters

ALTER TABLE encounters
ALTER COLUMN [start] DATETIME2;

ALTER TABLE encounters
ALTER COLUMN [stop] DATETIME2;


--- patients 
Select * from patients

ALTER TABLE patients
ALTER COLUMN BIRTHDATE DATETIME2 ;  

---- Medecations
select * from medications

ALTER TABLE medications
ALTER COLUMN [start] DATETIME2;

ALTER TABLE medications
ALTER COLUMN [stop] DATETIME2;

----- Conditins
Select * from conditions

ALTER TABLE conditions
ALTER COLUMN [start] DATETIME2;

ALTER TABLE conditions
ALTER COLUMN [stop] DATETIME2;




-------------------------------------------------- 4- Validate Referential Integrity
Select * from patients
Select * from encounters


SELECT *
FROM encounters e
LEFT JOIN patients p
ON e.PATIENT = p.id
WHERE p.id IS NULL;


----- referential integrity between patients and encounters perfect


SELECT *
FROM conditions c
LEFT JOIN encounters e
ON c.ENCOUNTER = e.id
WHERE e.id IS NULL;


----- referential integrity between encounters and conditions perfect





--------------------- 5- Typcasting

Select* from patients

ALTER TABLE patients 
Alter column INCOME FLOAT


--- all numeric and vitals are FLOAT