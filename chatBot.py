from flask import Flask, request, jsonify, render_template
import pyodbc

app = Flask(__name__, template_folder="templates", static_folder="static")

conn_str = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=DESKTOP-F3V4U4M;"
    "DATABASE=MedrikChatBot;"
    "Trusted_Connection=yes;"
)
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()

def find_answer_from_db(user_question):
    cursor.execute("SELECT answer FROM FAQs WHERE question LIKE ?", f"%{user_question}%")
    row = cursor.fetchone()
    if row:
        return row.answer
    return "پاسخی یافت نشد."

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/get_questions")
def get_questions():
    cursor.execute("SELECT DISTINCT question FROM FAQs")
    questions = [row[0] for row in cursor.fetchall()]
    return jsonify({"questions": questions})

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    user_question = data.get("question")
    if not user_question:
        return jsonify({"error": "سؤال ارسال نشده!"}), 400
    answer = find_answer_from_db(user_question)
    return jsonify({"answer": answer})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
