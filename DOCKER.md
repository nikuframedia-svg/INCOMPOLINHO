# PP1 — Correr com Docker

Guia para pôr o PP1 a funcionar em qualquer computador, **Linux** ou **Mac**,
sem instalar Python, Node ou dependências — só o Docker.

---

## 1. Pré-requisitos

- **Docker Engine** + **Docker Compose v2** (v2.24 ou mais recente).
  - Linux: instalar o [Docker Engine](https://docs.docker.com/engine/install/)
    (o plugin `docker compose` vem incluído).
  - Mac: instalar o [Docker Desktop](https://docs.docker.com/desktop/).
- Confirmar que está instalado:
  ```bash
  docker --version
  docker compose version
  ```

Não é preciso mais nada. Não é preciso Python, nem Node, nem pnpm.

---

## 2. Arrancar a aplicação

Dentro da pasta do projecto:

```bash
# 1. (opcional) criar o ficheiro de ambiente para o copiloto de IA
cp .env.example .env        # depois editar .env e pôr a chave OpenAI

# 2. construir e arrancar
docker compose up --build -d
```

Abrir no browser: **http://localhost:3000**

A flag `--build` constrói a imagem **localmente, para a arquitectura da
máquina onde está a correr**. É por isso que funciona tanto no Mac
(Apple Silicon / Intel) como num PC Linux x86-64 — cada um constrói a sua.
A primeira construção demora alguns minutos; as seguintes são quase imediatas.

---

## 3. Comandos do dia-a-dia

```bash
docker compose ps                 # estado do contentor (e healthcheck)
docker compose logs -f            # ver logs em tempo real
docker compose restart            # reiniciar
docker compose down               # parar e remover o contentor
docker compose up --build -d      # reconstruir após alterações ao código
```

Os dados (bases de dados de auditoria e aprendizagem) ficam no volume
`pp1-data` e **sobrevivem** a `down`/`up` e reconstruções. Para apagar
tudo e começar do zero:

```bash
docker compose down -v            # -v também remove o volume de dados
```

---

## 4. Carregar um ISOP

Há duas formas:

1. **Pela interface** — usar a zona de upload na aplicação (recomendado).
2. **Pela pasta partilhada** — colocar o ficheiro `.xlsx` na pasta `isop/`
   do projecto; fica disponível dentro do contentor em `/app/isop/`.

---

## 5. Copiloto de IA (opcional)

O planeamento, o Gantt, o simulador e os KPIs funcionam **sem qualquer
configuração**. Só o chat de IA precisa de uma chave:

1. `cp .env.example .env`
2. Editar `.env` e preencher `PP1_OPENAI_API_KEY`.
3. `docker compose up -d` (recarrega o ambiente).

Sem `.env` a aplicação arranca na mesma — apenas o chat fica indisponível.

---

## 6. Saúde e diagnóstico

O contentor tem um *healthcheck* embutido. Em `docker compose ps` a coluna
de estado mostra `healthy` quando tudo está operacional (~25 s após arrancar).

```bash
# testar o backend directamente
curl http://localhost:3000/api/copilot/health
# → {"status":"ok","has_data":false,"n_segments":0}
```

Se algo falhar, `docker compose logs -f` mostra os logs do Nginx e do
backend (uvicorn).

---

## 7. Publicar uma imagem multi-arquitectura (avançado)

Se quiseres distribuir uma imagem **já construída** (em vez de cada pessoa
fazer `--build`), tem de ser **multi-arquitectura**, senão uma imagem feita
no Mac (arm64) não corre num PC Linux (amd64). Usar o `buildx`:

```bash
docker buildx create --use --name pp1-builder        # uma só vez
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <utilizador>/pp1-scheduler:latest \
  --push .
```

Quem recebe a imagem só precisa de, no `docker-compose.yml`, trocar o
bloco `build:` por `image: <utilizador>/pp1-scheduler:latest` e correr
`docker compose up -d` — o Docker puxa automaticamente a variante certa
para a sua arquitectura.

**Para o caso Lisboa↔Mac, a via mais simples e robusta continua a ser
`docker compose up --build`** em cada máquina — sem registos nem chaves.

---

## 8. Resolução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `port is already allocated` | A porta 3000 está ocupada | Editar `docker-compose.yml`: `"3001:80"` e abrir `:3001` |
| `env file .env not found` | Docker Compose < 2.24 | Actualizar o Compose, ou correr `cp .env.example .env` |
| Página abre mas dá 502 | Backend ainda a arrancar | Esperar ~25 s; ver `docker compose logs -f` |
| `exec format error` ao correr uma imagem puxada | Imagem de arquitectura errada | Construir local com `--build` ou publicar multi-arch (secção 7) |
| Build falha em `pnpm install` | Lockfile dessincronizado | Garantir que `frontend/pnpm-lock.yaml` está actualizado |
