# Introspecta

Vitrine de ofertas do Mercado Livre com produtos que podem ajudar no conforto sensorial, na rotina e na organização de pessoas autistas e suas famílias.

O nome fica em `config.json` (campo `nome`). Para trocar, edite ali e rode a atualização.

## Instalação (roteiro que já funcionou no Gadget Bortone)
1. No GitHub, crie um repositório **vazio e público** (ex.: `introspecta`).
2. Faça `git clone` do repositório numa pasta ao lado, **fora** da pasta do zip.
3. Copie os arquivos deste projeto para a pasta clonada.
4. Renomeie `atualizar.bat.modelo` para `atualizar.bat` e coloque o ID e o Secret do app do Mercado Livre.
5. Rode `atualizar.bat`. Se algum item faltar, veja `log.txt`.
6. Rode `atualizar_e_publicar.bat`.
7. No GitHub: Settings > Pages > branch `main`, pasta `/docs`.

Cuidados:
- **Não publique a prévia de exemplo** (`python gerar_site.py --demo`).
- `atualizar.bat` fica no `.gitignore`; nunca suba nem envie em zip.
- Teste o site em janela anônima, para não ver versão guardada.
- Se o primeiro push for recusado em repositório novo: `git push -u --force origin main`.
- GitHub Actions não funciona para coletar (o Mercado Livre bloqueia os IPs).

## Ajuste fino
`python gerar_site.py --diagnostico` grava `diagnostico.txt` com as respostas reais da API. Envie esse arquivo e o `log.txt` para ajustar filtros e marcas.
