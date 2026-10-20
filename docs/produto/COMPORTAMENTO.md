# Comportamento — regras da fábrica no planeamento

> Regras de produto (o que o plano tem de respeitar). O contrato detalhado e as
> decisões com data estão em `AGENTS.md`, que prevalece em caso de conflito.
> Ecrãs e utilização: `docs/operator-guide.md` e `docs/manual-tecnico-funcional-incompol.md`.

Fábrica: Incompol (5 prensas, 59 ferramentas, ~94 SKUs, 14 clientes). Empresa: NIKUFRA.AI.

## ENTREGAS
Entregar a tempo é o primeiro objetivo **depois das leis físicas** (máquina,
ferramenta, equipa, calendário, material) e do lote económico numa só produção.
O lote económico numa só produção é **regra dura, acima da entrega a tempo**
(decisão do Luís, 13/10/2026; verificação `lot_split` no gate): se o lote
atrasa outra encomenda, move-se inteiro; nunca se parte para a salvar. Pode
atrasar uma entrega quando o lote não cabe inteiro antes do prazo (visto num
ensaio de 13/10, revisão 128, avaria grande da PRM031 a 16/10: uma entrega um
dia atrasada) e traz mais stock e produção mais cedo: +39% peças × dias e 44
entregas com mais de 30 dias de antecedência na carga de ISOP nova de 13/10;
+39% e 52 no recálculo F1 do golden master (AGENTS §1.1). Quando há
capacidade, o alvo é OTD = OTD-D = 100%.

- **OTD** (global) = total produzido >= total procura
- **OTD-D** (por dia) = em cada dia com procura, produção acumulada >= procura acumulada
- Uma melhoria automática nunca pode piorar **nenhuma** encomenda individual.
- **Subcontratadas (Luís, 14/10/2026):** só estão atrasadas se faltar stock
  no ecrã de Entregas no dia da entrega (peças contam no dia em que são
  feitas), em todo o sistema e sem opção. O motor continua a apontar para
  acabar 5 dias úteis antes (envio), mas falhar isso não é atraso nem
  aparece no ecrã (AGENTS §2).
- Se não há capacidade dentro da janela de material, o plano mantém e reporta
  os atrasos: nunca relaxar a janela, inventar stock ou violar física para
  mostrar 100%. Ex.: revisão 90 tem OTD 96,5% por falta real de capacidade
  na PRM042 (sem alternativa).

## DADOS ISOP

Colunas: A(Cliente) B(Nome) C(SKU) D(Designação) E(Lote Eco—HARD)
G(Máquina) H(Ferramenta) I(Peças/H) J(Pessoas) L(WIP) M(Gémea) N(Atraso)
O+(Datas ~80 dias—FONTE PRINCIPAL)

IGNORAR SEMPRE: F(Prz.Fabrico) e K(STOCK-A)

Valores NP nas datas:
- Positivo (preto) = STOCK REAL disponível
- Negativo (vermelho) = ENCOMENDA INDEPENDENTE (NÃO cumulativo)
  |valor| = qtd a produzir, data coluna = deadline
- Vazio = sem dados

Stock real = último positivo antes do primeiro negativo.
Lote económico: HARD — é o MÍNIMO; nunca múltiplos. Lote = max(lote económico,
necessidade) (decisão do Luís, 14/10/2026; AGENTS §2).

## LOTE ECONÓMICO = UMA PRODUÇÃO (decisão do Luís, 13/10/2026)
Regra da Incompol; detalhe no `AGENTS.md` §2 («Lote económico = uma produção»).
Estado: implementada a 13/10/2026 (contrato de material versão 3). Planos antigos
continuam válidos (não pedem «Recalcular»); o «Recalcular plano» redimensiona-os.
- Sempre que se produz um SKU, produz-se pelo menos o lote económico, numa só
  produção (um setup). O lote económico cumpre-se sempre.
- **Lote económico = mínimo, nunca múltiplos (14/10/2026, versão 4):** se a
  necessidade da entrega que abre o lote é maior do que o lote económico,
  produz-se essa quantidade (27 641 com lote de 23 040 → 27 641, não 46 080).
  Planos das versões 1-3 (arredondados) são reconstruídos pelo «Recalcular
  plano»; num replaneamento os lotes começados mantêm o tamanho antigo
  (regra 4) e contam como oferta já comprometida.
- A janela de 5 dias úteis de matéria-prima vale só para a PRIMEIRA entrega que
  o lote serve. As outras entregas que o lote cobre e o excedente não têm janela
  própria: considera-se que há MP para o lote económico inteiro.
- Nunca partir um lote em produções separadas. Se atrasar outra encomenda,
  move-se o lote inteiro (mais cedo, mais tarde ou para a máquina alternativa).
- Gémeas: o ciclo usa o `R` da primeira entrega de qualquer dos lados.
- Subcontratados (implementado a 14/10/2026): o lote inteiro vai ao
  subcontratado quando acaba e volta todo em fim do lote + prazo (dias úteis);
  todas as entregas do lote ficam prontas nesse dia; tem de acabar até ao
  último envio `H` da primeira entrega (`material_quantities.whole_lot_subcontract`).
- Um lote nunca para com tempo de turno livre pelo meio, nem é interrompido
  por outro trabalho; só uma avaria ou bloqueio sobre o tempo de trabalho
  entre as partes o desculpa. Lotes de planos antigos (v1-2) podem manter as
  produções que tinham, mas não ganhar outra.
- A janela por entrega (07–11/10/2026) partia os lotes e subiu os setups de
  ~3 para ~9 por dia; não voltar a ela.

## PEÇAS GÉMEAS
Mesma ferramenta + máquina, produção SIMULTÂNEA.
Quantidade por ciclo = a maior das necessidades dos dois lados (cada uma pelo
menos o seu lote económico, sem arredondar); os dois SKUs recebem essa quantidade.
Tempo = UMA execução (max(time_A, time_B), não dobro).
Surplus carry-forward independente por SKU.

## MÁQUINAS
PRM019(Grandes,21SKUs) PRM031(Grandes,20,Faurecia) PRM039(Grandes,28,+variedade)
PRM042(Médias,11,SEM ALTERNATIVA) PRM043(Grandes,14)
PRM020 — fora do âmbito da análise; não importar procura nem criar capacidade nesta máquina.

## TURNOS
Turno A: 07:00-15:30 (510 min) | Turno B: 15:30-00:00 (510 min)
DAY_CAP = 1020 min. Noite: SÓ EMERGÊNCIA.


## Utilização do planeador (decisões de 15–16/10/2026)
- **Recusas dizem porquê.** Uma alteração recusada mostra «Porquê:» com causas concretas (dia, hora, referência · ferramenta (máquina)), nunca só «Plano inválido: N conflitos» nem um alerta do browser.
- **Lotes fixados à mão** («Mover lote»): aparecem no topo como «N lotes fixados à mão» (os registos do que correu contam à parte, «N registados como feitos»), com «Soltar» / «Soltar todos». Um lote fixado é uma posição, não produção feita. Se um feriado, avaria ou ISOP o tornar impossível, é solto com o aviso «Soltei a alteração manual da Referência …: motivo».
- **Mover lote:** se o lote não couber seguido (só turnos, noites e feriados interrompem), é recusado na hora com horas precisas/livres e «Usar este início» (primeiro início onde cabe).
- **Registar o que correu (20/10/2026):** «Mover lote» para uma hora de hoje que já passou quer dizer «este lote correu desde esta hora». Antes de aplicar, a verificação diz em destaque «Vai ficar registado como já produzido desde HH:MM na <máquina>», o que estava planeado nessa máquina e não se fez (replaneado a partir de agora) e quando fica pronto. Aparece como «registado como feito desde …». Para corrigir, «Desfazer» (no mesmo dia, enquanto o trabalho replaneado ainda não começou; se já começou, diz porquê); «Soltar» tira a marca: a manhã fica igual; o resto é replaneado. Dias anteriores, antes do material ou com a máquina parada: recusado com mensagem clara. Uma avaria lançada depois que pare o lote antes da primeira peça solta o registo, com aviso.
- **«Recalcular plano»** apaga todas as alterações manuais (pede confirmação) e calcula de raiz; os lotes registados como feitos ficam (só um ISOP novo os tira; se não houver plano válido, um registo pode ser solto, com aviso).
- **Configuração:** todas as alterações vão para «N alterações por aplicar» («×» por linha). «Aplicar» faz um só recálculo e guarda; só pede justificação se o plano exigir aprovação. «Descartar» limpa. A lista sobrevive à navegação; o browser avisa ao fechar.
- **Desativar máquina** funciona sempre: o trabalho passa para a alternativa (o resto de lotes começados também; o feito fica). Referências sem máquina ativa saem do plano com o aviso «Sem máquina ativa: …» e contam como atrasadas. A linha da lista mostra o impacto antes de aplicar.
- **Lote começado** só muda de máquina se a dele deixar de poder ser usada (inativa ou não permitida).
- **Paragem no Gantt:** mostra atrasos/setups antes → depois e só depois aplica.
- **Planos / Desfazer:** cada versão tem nome e hora; «Desfazer» recua um passo por clique.
- **Stock:** detalhe com coluna Data; referência com ferramenta e a(s) prensa(s) que o plano usa.
