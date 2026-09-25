from __future__ import annotations


def link_accounts(connection) -> int:
    """Vincula a conta importada por arquivo à mesma conta vinda do Open Finance.

    O CSV do Nubank não traz número de conta, e a Pluggy usa ids próprios. Sem esse vínculo, a mesma
    conta aparece com dois apelidos e as movimentações são somadas duas vezes. Só vincula quando o par
    é inequívoco: na mesma instituição, uma única conta Open Finance e uma única conta de arquivo daquele tipo
    (com Nubank e Itaú conectados, cada banco forma seu próprio par).
    Roda depois de cada importação e sincronização, pois a importação de OFX regrava o apelido.
    """
    renamed = 0
    for account_type in ("BANK", "CREDIT"):
        pluggy = connection.execute(
            "SELECT institution, account_name FROM financial_account WHERE provider = 'pluggy' AND account_type = ?",
            (account_type,),
        ).fetchall()
        files = connection.execute(
            "SELECT id, institution, account_name FROM financial_account "
            "WHERE provider <> 'pluggy' AND account_type = ?",
            (account_type,),
        ).fetchall()
        for institution in {row["institution"] for row in files}:
            same_bank = [row for row in pluggy if row["institution"] == institution]
            same_files = [row for row in files if row["institution"] == institution]
            if len(same_bank) != 1 or len(same_files) != 1:
                continue
            target = same_bank[0]["account_name"]
            if same_files[0]["account_name"] != target:
                connection.execute(
                    "UPDATE financial_account SET account_name = ? WHERE id = ?", (target, same_files[0]["id"])
                )
                renamed += 1
    return renamed
