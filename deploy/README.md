# Publicação (deploy)

Serviços `systemd --user` desta app na máquina `nikufra-dev-01`:

| Unidade | O que faz | Registo |
|---|---|---|
| `incompolinho-backend.service` | uvicorn em `127.0.0.1:8010`. Ligação simbólica para `deploy/incompolinho-backend.service` | `.run-logs/backend.log` |
| `incompolinho-public-frontend.service` | `vite preview` em `127.0.0.1:53868`: serve `frontend/dist` e encaminha `/api` para o 8010. Ligação simbólica para `deploy/incompolinho-public-frontend.service` (depois da mudança única abaixo) | `.run-logs/frontend.log` |
| `incompolinho-public-tunnel.service` | Túnel rápido `cloudflared` para `127.0.0.1:53868`. Unidade transitória, criada com `systemd-run` | — |

**Não reiniciar o túnel.** Se for reiniciado, o link público `*.trycloudflare.com`
muda. Reiniciar o frontend não toca no túnel, porque a porta 53868 é a mesma.

Regras de publicação: `AGENTS.md` §7. Só se publica código que está num commit,
e só uma sessão de cada vez mexe na árvore de produção.

## Frontend: o link serve a versão final

Até aqui, o link público servia o **servidor de desenvolvimento** do Vite. Isso
trazia quatro problemas:

- cada ficheiro gravado ia logo para o link, mesmo a meio de uma alteração;
- a página recarregava-se sozinha, e quem estivesse a escrever perdia o texto;
- os pedidos apareciam em duplicado;
- os ficheiros-fonte ficavam acessíveis (`/src`, `/@fs`).

Agora o link serve a **versão compilada** (`frontend/dist`):

- não há recarregamentos automáticos;
- os ficheiros têm hash no nome;
- `/src`, `/@fs` e `/@vite/client` só devolvem a página inicial, nunca o
  conteúdo dos ficheiros.

**Gravar um ficheiro deixou de mudar o que a Incompol vê.** Só muda quando se
corre o script de compilação. Para desenvolver, usar `npm run dev` (porta 3000)
por túnel SSH.

> Na árvore de produção, **não correr `npm run build`**. Esse comando escreve
> diretamente em `frontend/dist`. Isso publica no momento, sem verificar o
> commit e sem troca atómica. Usar sempre o script abaixo.

### Publicar uma alteração do frontend

1. Pôr a alteração num commit e a árvore de produção nesse commit.
2. Compilar:

   ```bash
   cd /home/luis/projects/INCOMPOLINHO
   scripts/deploy/build_frontend.sh
   ```

   O script faz isto, por ordem:
   - recusa avançar se `frontend/` tiver alterações por guardar;
   - corre `tsc -b` e `vite build` para `frontend/dist.new`;
   - confirma que o resultado é a versão final;
   - troca `dist.new` por `dist`;
   - acrescenta uma linha a `.run-logs/frontend-build.log` com a data, o commit
     e o ficheiro de entrada.

   Se a compilação falhar, o `dist` anterior fica como estava.

   **A nova versão fica visível no carregamento seguinte da página**, porque o
   `vite preview` lê os ficheiros do disco a cada pedido. Quem tem a página
   aberta continua na versão antiga até recarregar.
3. Reiniciar o serviço. É o procedimento habitual e é **obrigatório** quando
   muda `frontend/vite.config.ts` ou o ficheiro da unidade. O link fica cerca
   de 2 s sem responder.

   ```bash
   systemctl --user restart incompolinho-public-frontend.service
   ```

4. Verificar:

   ```bash
   tail -1 .run-logs/frontend-build.log                             # commit e entry=
   curl -s http://127.0.0.1:53868/ | grep -o '/assets/index-[^"]*'  # igual ao entry=
   curl -s http://127.0.0.1:53868/ | grep -c '@vite/client'         # 0
   curl -s http://127.0.0.1:53868/api/data/today                    # data de hoje
   ```

**Voltar atrás:** pôr a árvore no commit anterior e correr o script outra vez.

### Mudança única: do modo de desenvolvimento para a versão final

Fazer isto uma só vez, depois de o merge estar na árvore de produção. Até lá, a
unidade em uso é um ficheiro normal em `~/.config/systemd/user/` que corre o
servidor de desenvolvimento.

```bash
cd /home/luis/projects/INCOMPOLINHO
# 1. Compilar primeiro. O frontend/dist que lá está é de 02/10 e está desatualizado.
scripts/deploy/build_frontend.sh
# 2. Guardar a unidade antiga (mesma convenção das outras cópias nesta pasta).
cp ~/.config/systemd/user/incompolinho-public-frontend.service \
   ~/.config/systemd/user/incompolinho-public-frontend.service.before-preview-20261012
# 3. Apontar a unidade para a versão do repositório e aplicar.
ln -sfn /home/luis/projects/INCOMPOLINHO/deploy/incompolinho-public-frontend.service \
   ~/.config/systemd/user/incompolinho-public-frontend.service
systemctl --user daemon-reload
systemctl --user restart incompolinho-public-frontend.service
systemctl --user status incompolinho-public-frontend.service --no-pager
```

Depois, fazer as verificações do passo 4 acima e abrir o link público.

**Desfazer:** usar `mv` e não `cp`. Um `cp` escreveria através da ligação
simbólica, por cima do ficheiro do repositório.

```bash
mv -f ~/.config/systemd/user/incompolinho-public-frontend.service.before-preview-20261012 \
      ~/.config/systemd/user/incompolinho-public-frontend.service
systemctl --user daemon-reload
systemctl --user restart incompolinho-public-frontend.service
```

## Backend: registo de pedidos com hora

O `ExecStart` de `deploy/incompolinho-backend.service` passa
`--log-config deploy/uvicorn-logging.json`. Cada pedido fica registado com a
data e a hora:

```
2026-10-12 12:28:27+0200 INFO 203.0.113.9:0 "GET /api/data/today HTTP/1.1" 200 OK
2026-10-12 12:28:38+0200 WARNING backend.transform.twins Twin BFP100: found ... in current ISOP
```

Como ler estas linhas:

- **Hora:** é a do servidor (`Europe/Berlin`), com o desvio indicado (`+0200`
  no verão). Em Portugal continental é uma hora a menos.
- **IP:** é o do visitante, enviado pelo `cloudflared` em `X-Forwarded-For`. O
  `:0` é só o lugar da porta.
- **Avisos e erros da aplicação** também passam a ter hora. As linhas de
  `backend.loading` mantêm o formato próprio.
- **Linhas antigas:** as que foram escritas antes desta mudança continuam sem
  hora.

Ver o uso do ecrã "Hoje", por exemplo:

```bash
grep '"GET /api/data/today' .run-logs/backend.log | awk '{print $1, $2, $4}'
```

**Quando entra em vigor.** A unidade do backend é uma ligação simbólica para
este repositório. Depois do merge, a mudança entra em vigor com
`systemctl --user daemon-reload` e o reinício seguinte do backend, mesmo que
esse reinício seja por outra razão.

Reiniciar o backend é uma publicação: antes, fazer cópia de segurança dos dados
e explicar ao Luís (`AGENTS.md` §7). Se o ficheiro de configuração faltar ou
estiver inválido, o backend não arranca. Confirmar antes de reiniciar:

```bash
.venv/bin/python -c "import json, logging.config; logging.config.dictConfig(json.load(open('deploy/uvicorn-logging.json'))); print('ok')"
```

**Desfazer:** retirar `--log-config ...` do `ExecStart`, depois correr
`daemon-reload` e reiniciar o backend.
