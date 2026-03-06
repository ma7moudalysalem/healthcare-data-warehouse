
---------------- patients

select * from Patients


UPDATE patients
SET name =
REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
name,
'0',''),'1',''),'2',''),'3',''),'4',''),
'5',''),'6',''),'7',''),'8',''),'9','');


Update patients 
set city='Boston'
where city is null


-----------------

-- Claims



select* from Claims

Alter table claims
Alter column amount_billed FLOAT

Alter table claims
Alter column amount_paid FLOAT


---------------------
-- encounter

select * from encounters



Alter table Encounters
alter column total_cost FLOAT


-------------------

--- Medications

select * from Medications

Alter Table Medications
Alter column cost FLOAT


------------------------

-- providers

 select * from Providers

 UPDATE Providers
SET name =
REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
name,
'0',''),'1',''),'2',''),'3',''),'4',''),
'5',''),'6',''),'7',''),'8',''),'9','');


---------------------

-- vital signs

Alter table Vital_Signs
Alter column heart_rate Float

Alter table Vital_Signs
Alter column systolic_bp Float

Alter table Vital_Signs
Alter column diastolic_bp Float

Alter table Vital_Signs
Alter column temp Float

Alter table Vital_Signs
Alter column spo2 Float


select * from Vital_Signs
--------------------------

---- conditions 
select * from Conditions

Alter table conditions
Add status NVARCHAR(50)

Update Conditions
Set status = 
CASE 
when onset_date=resolved_date Then 'Chronic Conditions'
Else 'Non-Chronic Conditions'
END





