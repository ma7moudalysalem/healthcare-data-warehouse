

--------------------------------------------------
-- Patients
--------------------------------------------------
CREATE TABLE Patients (
    patient_id UNIQUEIDENTIFIER PRIMARY KEY,
    name NVARCHAR(150) ,
    birth_date DATE NOT NULL,
    gender NVARCHAR(20),
    race NVARCHAR(50),
    city NVARCHAR(100),
    state NVARCHAR(100),
    insurance_type NVARCHAR(100)
);

--------------------------------------------------
-- Providers
--------------------------------------------------
CREATE TABLE Providers (
    provider_id UNIQUEIDENTIFIER PRIMARY KEY,
    name NVARCHAR(150) NOT NULL,
    specialty NVARCHAR(100),
    organization NVARCHAR(150),
    city NVARCHAR(100)
);

--------------------------------------------------
-- Encounters
--------------------------------------------------
CREATE TABLE Encounters (
    encounter_id UNIQUEIDENTIFIER PRIMARY KEY,
    patient_id UNIQUEIDENTIFIER NOT NULL,
    provider_id UNIQUEIDENTIFIER NULL,
    encounter_type NVARCHAR(100),
    start_date DATETIME2,
    end_date DATETIME2,
    total_cost DECIMAL(12,2),

    CONSTRAINT FK_Encounters_Patients
        FOREIGN KEY (patient_id) REFERENCES Patients(patient_id),

    CONSTRAINT FK_Encounters_Providers
        FOREIGN KEY (provider_id) REFERENCES Providers(provider_id)
);

--------------------------------------------------
-- Conditions
--------------------------------------------------
CREATE TABLE Conditions (
    condition_id  int IDENTITY(1,1) PRIMARY KEY ,
    patient_id UNIQUEIDENTIFIER NOT NULL,
    encounter_id UNIQUEIDENTIFIER NOT NULL,
    icd10_code NVARCHAR(20),
    description NVARCHAR(255),
    onset_date DATE,
    resolved_date DATE,

    CONSTRAINT FK_Conditions_Patient
        FOREIGN KEY (patient_id) REFERENCES Patients(patient_id),

    CONSTRAINT FK_Conditions_Encounter
        FOREIGN KEY (encounter_id) REFERENCES Encounters(encounter_id)
);




--------------------------------------------------
-- Medications
--------------------------------------------------
CREATE TABLE Medications (
    medication_id INT IDENTITY(1,1) PRIMARY KEY,
    patient_id UNIQUEIDENTIFIER NOT NULL,
    encounter_id UNIQUEIDENTIFIER NOT NULL,
    drug_code NVARCHAR(50),
    description NVARCHAR(300),
    start_date DATE,
    stop_date DATE,
    cost DECIMAL(12,2),

    CONSTRAINT FK_Medications_Patient
        FOREIGN KEY (patient_id) REFERENCES Patients(patient_id),

    CONSTRAINT FK_Medications_Encounter
        FOREIGN KEY (encounter_id) REFERENCES Encounters(encounter_id)
);

Drop table Medications

--------------------------------------------------
-- Claims
--------------------------------------------------
CREATE TABLE Claims (
    claim_id UNIQUEIDENTIFIER PRIMARY KEY,
    patient_id UNIQUEIDENTIFIER NOT NULL,
    encounter_id UNIQUEIDENTIFIER NOT NULL,
    payer_name NVARCHAR(150),
    amount_billed DECIMAL(12,2),
    amount_paid DECIMAL(12,2),
    status NVARCHAR(50),

    CONSTRAINT FK_Claims_Patient
        FOREIGN KEY (patient_id) REFERENCES Patients(patient_id),

    CONSTRAINT FK_Claims_Encounter
        FOREIGN KEY (encounter_id) REFERENCES Encounters(encounter_id)
);

--------------------------------------------------
-- Vital Signs
--------------------------------------------------
CREATE TABLE Vital_Signs (
    vital_id NVARCHAR(50) PRIMARY KEY,
    patient_id UNIQUEIDENTIFIER NOT NULL,
    heart_rate INT,
    systolic_bp INT,
    diastolic_bp INT,
    temp DECIMAL(4,1),
    spo2 INT,
    [timestamp] DATETIME2,

    CONSTRAINT FK_Vitals_Patient
        FOREIGN KEY (patient_id) REFERENCES Patients(patient_id)
);


Drop table Vital_Signs