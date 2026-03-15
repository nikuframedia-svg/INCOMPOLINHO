# PP1 — ProdPlan ONE

**Demo Incompol · NIKUFRA.AI · Março 2026**

Plataforma de planeamento de produção com IA para fábricas de estampagem metálica.

## Arranque Rápido

### 1. Configurar API Key OpenAI

```bash
# Linux/Mac
export OPENAI_API_KEY="sk-..."

# Windows
set OPENAI_API_KEY=sk-...
```

> **Nota:** Sem API key o planeamento funciona normalmente. Apenas o chat IA fica desactivado.

### 2. Instalar e Arrancar

```bash
pip install -r requirements.txt
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Ou usar o script:
```bash
# Linux/Mac
chmod +x start.sh && ./start.sh

# Windows
start.bat
```

### 3. Abrir

Navegar para **http://localhost:8000**

O ISOP da Incompol carrega automaticamente. Para carregar outro ISOP, usar o endpoint `POST /api/upload-isop`.

## O Que Faz

### Scheduling com Regras de Fábrica
- **Backward scheduling**: produção 1-2 dias antes da entrega (just-in-time)
- **Lote económico**: nunca produz abaixo do lote mínimo
- **Material affinity**: refs com MP partilhada → mesma máquina
- **Peças gémeas**: sequenciamento automático

### Alertas Inteligentes
- 🔴 **ATRASO** — já em falta (prioridade máxima)
- 🔴 **Urgente** — ruptura dentro de 2 dias
- 🟡 **Atenção** — ruptura dentro de 5 dias

### Chat IA (GPT-4o)
O planeador fala em português e o sistema executa:
- "Agrupa a ref 262 e 170 na PRM019, partilham matéria-prima"
- "Qual é a carga da PRM031?"
- "Porque é que a ref 769 está em risco?"
- "Muda o lote económico da 556 para 9520"
- "Adiciona uma máquina PRM050 com 3 turnos"

Cada alteração recalcula o plano automaticamente.

## Estrutura

```
pp1-demo/
├── backend/
│   ├── main.py           # FastAPI server
│   ├── isop_parser.py    # Parser Excel ISOP
│   ├── scheduler.py      # Motor de scheduling
│   ├── llm_engine.py     # OpenAI GPT-4o + function calling
│   ├── models.py         # Data models
│   └── static/
│       └── index.html    # Frontend (single file)
├── requirements.txt
├── start.sh
├── start.bat
└── README.md
```

## API Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/load-default` | POST | Carrega ISOP default |
| `/api/upload-isop` | POST | Upload novo ISOP |
| `/api/dashboard` | GET | KPIs e resumo |
| `/api/schedule` | GET | Plano completo |
| `/api/schedule/{machine}` | GET | Plano por máquina |
| `/api/alerts` | GET | Alertas activos |
| `/api/references` | GET | Todas as referências |
| `/api/references/{ref}` | GET | Detalhe de referência |
| `/api/machines` | GET | Carga de máquinas |
| `/api/chat` | POST | Chat com IA |
| `/api/health` | GET | Estado do sistema |

## Tools do LLM

O GPT-4o tem acesso a 10 ferramentas via function calling:

1. `adicionar_maquina` — nova prensa
2. `definir_lote_economico` — alterar lote mínimo
3. `agrupar_material` — refs com MP partilhada → mesma máquina
4. `mover_referencia` — reassignar máquina
5. `definir_buffer_producao` — dias antes da entrega
6. `recalcular_plano` — recalcular scheduling
7. `explicar_referencia` — detalhe com cobertura
8. `ver_carga_maquinas` — utilização
9. `ver_alertas` — filtrar por severidade
10. `remover_maquina` — indisponibilizar

---

**NIKUFRA.AI** · Pleasant Gadget Lda · NIF 519219732
