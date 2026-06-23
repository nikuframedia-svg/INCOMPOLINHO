# PP1 — Correr com Docker

Guia para pôr o PP1 a funcionar em qualquer computador, **Linux** ou **Mac**,
sem instalar Python, Node ou dependências — só o Docker. Por defeito, a app
fica exposta apenas em `localhost`.

---

## 1. Pré-requisitos

- **Docker Engine** + **Docker Compose v2** (qualquer versão recente serve).
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
# 1. criar o ficheiro de ambiente (basta uma vez)
cp .env.example .env        # opcional: editar .env e pôr a chave OpenAI

# 2. construir e arrancar
docker compose up --build -d
```

> O passo 1 é necessário porque o `docker-compose.yml` lê o `.env`. O
> ficheiro pode ficar com a chave por preencher — só o chat de IA depende
> dela; o resto da aplicação funciona na mesma.

Abrir no browser: **http://localhost:3000**

O `docker-compose.yml` publica a porta em `127.0.0.1` apenas. Isto impede que
a aplicação fique acessível automaticamente a partir da rede. Para mudar a
porta local, editar `.env`:

```bash
PP1_HTTP_PORT=3001
```

A flag `--build` constrói a imagem **localmente, para a arquitectura da
máquina onde está a correr**. É por isso que funciona tanto no Mac
(Apple Silicon / Intel) como num PC Linux x86-64 — cada um constrói a sua.
A primeira construção demora alguns minutos; as seguintes são quase imediatas.

---

## 3. Mac → Linux: build no Linux

Esta é a via recomendada para passar de um Mac para um Linux: copiar/clonar o
projecto no Linux e construir a imagem lá. Assim o Docker cria automaticamente
uma imagem para a arquitectura certa da máquina Linux.

No Linux:

```bash
# 1. confirmar arquitectura do host
uname -m

# 2. preparar pasta de deploy
sudo mkdir -p /opt/pp1-scheduler
sudo chown "$USER":"$USER" /opt/pp1-scheduler
cd /opt/pp1-scheduler

# 3A. se houver repositório Git
git clone <repo-url> .

# 3B. se for cópia directa a partir do Mac, usar rsync a partir do Mac:
# rsync -az \
#   --exclude '.git/' \
#   --exclude '.venv/' \
#   --exclude 'frontend/node_modules/' \
#   --exclude 'frontend/dist/' \
#   --exclude 'data/' \
#   --exclude '.env' \
#   /Users/martimnicolau/Documents/Incompol/ user@linux-host:/opt/pp1-scheduler/

# 4. configurar ambiente no Linux
cp .env.example .env
mkdir -p isop

# 5. construir e arrancar
docker compose up --build -d

# 6. validar saúde localmente no Linux
docker compose ps
curl http://localhost:3000/api/copilot/health
```

Se alteraste `PP1_HTTP_PORT` no `.env`, usa essa porta no `curl` e no túnel
SSH.

Como a porta fica presa a `127.0.0.1`, para usar a app a partir do Mac sem
expor a porta na rede:

```bash
ssh -L 3000:localhost:3000 user@linux-host
```

Depois abrir no Mac: **http://localhost:3000**.

Não copiar o `.env` real por Git nem por canais inseguros. Criar o `.env` no
Linux e preencher a chave OpenAI apenas se o copiloto de IA for necessário.

---

## 4. Comandos do dia-a-dia

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

## 5. Carregar um ISOP

Há duas formas:

1. **Pela interface** — usar a zona de upload na aplicação (recomendado).
2. **Pela pasta partilhada** — colocar o ficheiro `.xlsx` na pasta `isop/`
   do projecto; fica disponível dentro do contentor em `/app/isop/`.

---

## 6. Copiloto de IA (opcional)

O planeamento, o Gantt, o simulador e os KPIs funcionam **sem qualquer
configuração**. Só o chat de IA precisa de uma chave:

1. `cp .env.example .env` (se ainda não o fizeste — ver secção 2).
2. Editar `.env` e preencher `PP1_OPENAI_API_KEY`.
3. `docker compose up -d` (recarrega o ambiente).

Com o `.env` sem chave válida a aplicação arranca na mesma — apenas o
chat fica indisponível.

---

## 7. Saúde e diagnóstico

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

## 8. Publicar uma imagem multi-arquitectura (avançado)

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

## 9. Backup, restore e resolução de problemas

Backup dos dados persistentes, sem depender do nome real do volume Docker:

```bash
docker compose exec -T pp1 tar czf - -C /app/data . > pp1-data-backup.tgz
```

Restore para o contentor atual:

```bash
docker compose cp pp1-data-backup.tgz pp1:/tmp/pp1-data-backup.tgz
docker compose exec -T pp1 sh -c "find /app/data -mindepth 1 -delete && tar xzf /tmp/pp1-data-backup.tgz -C /app/data"
docker compose restart
```

| Sintoma | Causa provável | Solução |
|---|---|---|
| `port is already allocated` | A porta 3000 está ocupada | Editar `.env`: `PP1_HTTP_PORT=3001` e abrir `:3001` |
| `env file .env not found` | O `.env` não existe | Correr `cp .env.example .env` (secção 2, passo 1) |
| Página abre mas dá 502 | Backend ainda a arrancar | Esperar ~25 s; ver `docker compose logs -f` |
| Não abre por `http://IP-DO-LINUX:3000` | A porta está presa a `127.0.0.1` | Usar túnel SSH: `ssh -L 3000:localhost:3000 user@linux-host` |
| `exec format error` ao correr uma imagem puxada | Imagem de arquitectura errada | Construir local com `--build` ou publicar multi-arch (secção 8) |
| Build falha em `pnpm install` | Lockfile dessincronizado | Garantir que `frontend/pnpm-lock.yaml` está actualizado |
