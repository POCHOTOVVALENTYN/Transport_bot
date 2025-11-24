import requests

r = requests.get("https://api.eway.in.ua/", params={
    "login": "odesainclusive",
    "password": "ndHdy2Ytw2Ois",
    "function": "user.GetMyInfo",
    "format": "json"
})

print(r.json())