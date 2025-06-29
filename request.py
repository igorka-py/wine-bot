import requests

try:
    with requests.get(url='http://httpbin.org/get') as response:
        response.raise_for_status()  # Проверка на ошибки HTTP
        print(type(response))  # <class 'requests.models.Response'>
except requests.exceptions.RequestException as e:
    print(f"Ошибка при выполнении запроса: {e}")
