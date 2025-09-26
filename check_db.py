import sqlite3

conn = sqlite3.connect('tg_archive.db')
cursor = conn.cursor()

# Проверим темы
cursor.execute("SELECT COUNT(*) FROM topics")
topics_count = cursor.fetchone()[0]
print(f"Тем: {topics_count}")

# Проверим сообщения
cursor.execute("SELECT COUNT(*) FROM messages")
messages_count = cursor.fetchone()[0]
print(f"Сообщений: {messages_count}")

# Проверим пользователей
cursor.execute("SELECT COUNT(*) FROM users")
users_count = cursor.fetchone()[0]
print(f"Пользователей: {users_count}")

# Пример сообщения
cursor.execute("SELECT * FROM messages LIMIT 100")
msg = cursor.fetchone()
if msg:
    print(f"Пример сообщения: ID={msg[1]}, Text='{msg[4][:50]}...'")

conn.close()
