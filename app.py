from flask import Flask, render_template, request, redirect, session
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "un_codice_super_segreto123"  # Cambialo in produzione!

@app.route("/")
def index():
    df = pd.read_csv("log/log.csv", parse_dates=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    timestamps = df["timestamp"].tolist()
    values = df["mV"].tolist()
    return render_template("index.html", labels=timestamps, values=values)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        password = request.form["password"]
        citta = request.form["citta"]
        eta = request.form["eta"]
        data = [nome, email, password, citta, eta, datetime.now().strftime("%Y-%m-%d %H:%M")]
        file_path = "utenti_web.csv"
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                f.write("nome,email,password,citta,eta,data_reg\n")
        with open(file_path, "a") as f:
            f.write(",".join(data) + "\n")
        session["nome"] = nome
        return redirect("/dashboard")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        if os.path.exists("utenti_web.csv"):
            with open("utenti_web.csv", "r") as f:
                next(f)  # salta intestazione
                for riga in f:
                    campi = riga.strip().split(",")
                    if email == campi[1] and password == campi[2]:
                        session["nome"] = campi[0]
                        return redirect("/dashboard")
        return "❌ Email o password non corretti"
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    nome = session.get("nome", "utente")
    return render_template("dashboard.html", nome=nome)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
    
if __name__ == "__main__":
    app.run(debug=True)
