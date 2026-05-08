import subprocess
import sys
import os

# Auto-install fpdf2 if not present
try:
    from fpdf import FPDF
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fpdf2"])
    from fpdf import FPDF

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "demo-data")
os.makedirs(OUTPUT_DIR, exist_ok=True)


class ResumePDF(FPDF):
    def name_block(self, name, contact):
        self.set_font("Helvetica", "B", 20)
        self.cell(0, 10, name, ln=True, align="C")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, contact, ln=True, align="C")
        self.ln(3)

    def section(self, title):
        self.ln(2)
        self.set_fill_color(220, 220, 220)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, title.upper(), ln=True, fill=True)
        self.ln(1)

    def entry(self, left, right, subtitle=""):
        self.set_font("Helvetica", "B", 10)
        # Calculate widths
        right_w = self.get_string_width(right) + 2
        left_w = self.w - self.l_margin - self.r_margin - right_w
        self.cell(left_w, 5, left)
        self.set_font("Helvetica", "", 10)
        self.cell(right_w, 5, right, ln=True, align="R")
        if subtitle:
            self.set_font("Helvetica", "I", 9)
            self.cell(0, 4, subtitle, ln=True)

    def bullet(self, text):
        self.set_font("Helvetica", "", 9.5)
        self.set_x(self.l_margin + 4)
        self.multi_cell(0, 4.5, "- " + text)

    def skills_row(self, label, items):
        self.set_font("Helvetica", "B", 9.5)
        self.cell(33, 5, label + ":")
        self.set_font("Helvetica", "", 9.5)
        remaining = self.w - self.r_margin - self.x
        self.multi_cell(remaining, 5, items)
        # Ensure cursor is reset to left margin for next row
        self.set_x(self.l_margin)


# ─── Jamie Park ────────────────────────────────────────────────────────────────

def build_jamie():
    pdf = ResumePDF(format="Letter")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    pdf.name_block(
        "Jamie Park",
        "jamiepark359@gmail.com  |  (734) 555-0192  |  linkedin.com/in/jamiepark  |  github.com/jamiepark",
    )

    # Education
    pdf.section("Education")
    pdf.entry(
        "University of Michigan  -  B.S. Computer Science & Statistics",
        "Aug 2020 - May 2024",
        "GPA: 3.72 / 4.00",
    )
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_x(pdf.l_margin + 4)
    pdf.multi_cell(
        0,
        4.5,
        "Coursework: Machine Learning, Deep Learning, Statistical Inference, Database Systems, "
        "Data Structures & Algorithms, Probability Theory",
    )

    # Work Experience
    pdf.section("Work Experience")
    pdf.entry("Data Analytics Intern  -  ShipFast Logistics", "May 2023 - Aug 2023")
    pdf.bullet("Built 6 Tableau dashboards tracking delivery KPIs across 12 regional hubs, reducing manual reporting time by 40%")
    pdf.bullet("Wrote SQL queries against a PostgreSQL database to extract and aggregate shipment delay data for weekly operations review")
    pdf.bullet("Automated weekly Excel summary reports using Python and openpyxl, eliminating a 3-hour recurring manual process")

    # Projects
    pdf.section("Projects")

    pdf.entry("Sentiment Classifier (Undergraduate Thesis)", "Jan 2024 - Apr 2024")
    pdf.bullet("Fine-tuned a BERT model on 50,000 Amazon product reviews for multi-class sentiment classification (Positive/Neutral/Negative)")
    pdf.bullet("Achieved 91.3% accuracy on held-out test set, outperforming TF-IDF + Logistic Regression baseline (82.1%)")
    pdf.bullet("Stack: Python, PyTorch, HuggingFace Transformers, Scikit-learn, Jupyter Notebook")

    pdf.ln(1)
    pdf.entry("Movie Recommendation System", "Sep 2023 - Dec 2023")
    pdf.bullet("Implemented collaborative filtering via matrix factorization (ALS) trained on the MovieLens 1M dataset")
    pdf.bullet("Exposed recommendations through a REST API; evaluated with RMSE and precision@k metrics")
    pdf.bullet("Stack: Python, NumPy, Pandas, Scikit-learn, Flask, Git")

    pdf.ln(1)
    pdf.entry("Campus Event Multi-Label Classifier", "Feb 2023 - Apr 2023")
    pdf.bullet("Built a multi-label text classifier to auto-tag university event listings using Logistic Regression and Random Forest")
    pdf.bullet("Scraped and cleaned 4,000 event records; achieved F1-score of 0.84 across 8 categories")
    pdf.bullet("Stack: Python, Scikit-learn, BeautifulSoup, Pandas")

    # Skills
    pdf.section("Skills")
    pdf.skills_row("Languages", "Python, R, SQL, Bash")
    pdf.skills_row("ML / AI", "PyTorch, HuggingFace Transformers, Scikit-learn, NumPy, Pandas, Matplotlib")
    pdf.skills_row("Data & Viz", "Tableau, Jupyter Notebook, PostgreSQL, openpyxl")
    pdf.skills_row("Tools", "Git, GitHub, VS Code, Linux")

    out_path = os.path.join(OUTPUT_DIR, "jamie_park_resume.pdf")
    pdf.output(out_path)
    return out_path


# ─── Rachel Okonkwo ────────────────────────────────────────────────────────────

def build_rachel():
    pdf = ResumePDF(format="Letter")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    pdf.name_block(
        "Rachel Okonkwo",
        "rachel.okonkwo@email.com  |  (202) 555-0347  |  linkedin.com/in/rachelokonkwo  |  New York, NY",
    )

    # Professional Summary
    pdf.section("Professional Summary")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(
        0,
        5,
        "Senior Financial Analyst with 7 years of experience in quantitative financial modelling, SQL-driven reporting, "
        "and data automation at a commercial bank. Recently completed the Andrew Ng Machine Learning Specialization and "
        "applied Python-based automation to eliminate recurring reporting overhead. Seeking to transition into a Data "
        "Scientist role in FinTech, leveraging deep domain expertise in financial data alongside a growing ML foundation.",
    )

    # Work Experience
    pdf.section("Work Experience")

    pdf.entry("Senior Financial Analyst  -  Meridian Bank", "Mar 2021 - Present")
    pdf.bullet("Designed and maintained 15+ Excel (VBA) financial models supporting quarterly P&L reporting across a $2.4B commercial loan portfolio")
    pdf.bullet("Wrote complex SQL queries (joins, window functions, CTEs) against Oracle DB to extract, transform, and reconcile data across 8 business lines")
    pdf.bullet("Automated monthly regulatory reporting package in Python (Pandas, openpyxl), cutting preparation time from 8 hours to 45 minutes")
    pdf.bullet("Built a credit risk scoring model in Excel applying logistic regression principles; reduced manual loan review queue by 30%")

    pdf.ln(1)
    pdf.entry("Financial Analyst  -  Meridian Bank", "Jun 2018 - Feb 2021")
    pdf.bullet("Produced weekly performance dashboards in Tableau for senior management, tracking 20+ KPIs across retail and commercial divisions")
    pdf.bullet("Maintained SQL-based data pipelines feeding the firm's monthly variance analysis reports")
    pdf.bullet("Completed internal data governance certification covering data quality standards and lineage documentation")

    # Projects & Self-Directed Learning
    pdf.section("Projects & Self-Directed Learning")

    pdf.entry("Python Report Automation Tool", "2022 - Present")
    pdf.bullet("Built an internal CLI tool that ingests raw transaction exports, applies business rules, and outputs formatted Excel reports")
    pdf.bullet("Reduced a recurring 8-hour manual task to a 45-minute automated run; adopted by 3 colleagues")
    pdf.bullet("Stack: Python, Pandas, openpyxl, argparse")

    pdf.ln(1)
    pdf.entry("Machine Learning Specialization  -  Coursera (Andrew Ng / DeepLearning.AI)", "Sep 2023 - Feb 2024")
    pdf.bullet("Completed all 3 courses: Supervised ML, Advanced Learning Algorithms, Unsupervised Learning & Recommenders")
    pdf.bullet("Implemented linear/logistic regression, neural networks, decision trees, k-means, and collaborative filtering from scratch in Python and NumPy")
    pdf.bullet("Capstone: loan default prediction model on synthetic bank data using Scikit-learn (AUC-ROC 0.81)")

    # Education
    pdf.section("Education")
    pdf.entry(
        "Georgetown University  -  B.S. Finance, Minor: Mathematics",
        "Aug 2013 - May 2017",
        "GPA: 3.61 / 4.00",
    )

    # Skills
    pdf.section("Skills")
    pdf.skills_row("Languages", "SQL (Oracle, PostgreSQL), Python, VBA, Bash (basic)")
    pdf.skills_row("Python Libs", "Pandas, NumPy, Scikit-learn, openpyxl, Matplotlib")
    pdf.skills_row("Data & Viz", "Tableau, Excel (advanced), Bloomberg Terminal, Jupyter Notebook")
    pdf.skills_row("Finance", "Financial modelling, credit risk, DCF analysis, variance analysis, regulatory reporting")
    pdf.skills_row("Tools", "Git, Jira, Confluence")

    out_path = os.path.join(OUTPUT_DIR, "rachel_okonkwo_resume.pdf")
    pdf.output(out_path)
    return out_path


if __name__ == "__main__":
    jamie_path = build_jamie()
    print(f"Generated: {jamie_path}")

    rachel_path = build_rachel()
    print(f"Generated: {rachel_path}")

    print("Done.")
