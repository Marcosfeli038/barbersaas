from pyngrok import ngrok

public_url = ngrok.connect(8000)
print("URL Pública do ngrok:", public_url)

# Mantém o script a correr para o túnel não cair
input("Pressiona Enter para fechar o túnel...")