# FinanceOS

FinanceOS is a personal financial intelligence platform built using Python and Streamlit. It enables users to upload financial datasets, automatically detect dataset structures, analyze spending patterns, track budgets, monitor financial health, and generate actionable insights through interactive dashboards.

---

## Features

* Automatic Financial Dataset Detection
* Smart Column Mapping
* Transaction Tracking
* Budget Management
* Financial Health Score
* Spending & Savings Analysis
* Category Intelligence
* Behavioral Insights
* Interactive Dashboards
* Excel Report Export
* Tracker Mode
* Analyzer Mode

---

## Tech Stack

* Python
* Streamlit
* Pandas
* Plotly
* SQLite
* OpenPyXL

---

## Project Structure

```text
FinanceOS/
│
├── assets/
├── core/
│   ├── analyzer_engine.py
│   ├── charts.py
│   ├── db.py
│   ├── insights.py
│   ├── metrics.py
│   └── tracker_engine.py
│
├── data/
├── app.py
├── requirements.txt
└── README.md
```

---

## Setup Instructions

### Step 1: Clone the Repository

```bash
git clone https://github.com/divyatwork1-web/FinanceOS.git
```

### Step 2: Open the Project Folder

Open the project folder in:

* Visual Studio Code (Recommended)
* PyCharm
* Any Python IDE

Make sure you are inside the folder containing:

```text
app.py
requirements.txt
```

---

### Step 3: Install Dependencies

Open a terminal in the project folder and run:

```bash
pip install -r requirements.txt
```

If you receive a pip error, try:

```bash
python -m pip install -r requirements.txt
```

---

### Step 4: Run FinanceOS

Open a terminal in the same folder as `app.py` and run:

```bash
streamlit run app.py
```

If Streamlit is not installed:

```bash
pip install streamlit
```

Then run:

```bash
streamlit run app.py
```

---

### Step 5: Open the Application

After running the command, Streamlit will generate a local URL similar to:

```text
http://localhost:8501
```

Open this URL in your browser.

---

## How to Use

### 1. Launch FinanceOS

Run:

```bash
streamlit run app.py
```

---

### 2. Upload an Excel File

Click:

```text
Upload Excel File (.xlsx)
```

FinanceOS currently expects Excel files (.xlsx).

---

### 3. Review Dataset Detection

FinanceOS automatically:

* Detects dataset type
* Identifies transaction fields
* Maps financial columns
* Standardizes the dataset format

If required, manually adjust the column mappings.

---

### 4. Choose a Mode

#### Tracker + Analyzer

Use this mode to:

* Add transactions
* Edit transactions
* Manage budgets
* Analyze finances

#### Analyzer Only

Use this mode for:

* Spending analysis
* Financial insights
* Health score analysis
* Dashboard reporting

---

### 5. Explore Insights

Available sections include:

* Financial Overview
* Spending Analysis
* Savings Analysis
* Category Intelligence
* Budget Tracking
* Financial Health Score
* Behavioral Insights
* Reports

---

## Screenshots

Screenshots of the application are available in the `assets` folder.

---

## Author

Divyasree T
