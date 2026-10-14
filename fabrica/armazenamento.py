"""Onde fica o vídeo pronto durante os 3 dias de entrega (PLANO-VPS.md).

Cloudflare R2 (compatível com S3) quando o .env tem FABRICA_R2_ENDPOINT, FABRICA_R2_BUCKET, FABRICA_R2_ACCESS_KEY e
FABRICA_R2_SECRET_KEY: o vídeo sobe para lá ao terminar e o cliente baixa por um link assinado, sem pesar na banda da
VPS (o R2 não cobra a saída). Sem essas chaves (desenvolvimento, testes), uma pasta local, servida pela API
(/v1/videos/{id}/arquivo).

O objeto guardado no banco (videos.objeto) é a chave; o link é feito na hora do pedido, válido até o vídeo expirar
(o S3 aceita no máximo 7 dias, e o prazo daqui é 3). Uma regra de ciclo de vida no bucket apagando com mais de 3 dias
é a segunda garantia da limpeza (limpeza_vps.py é a primeira).
"""
import os
import shutil
from pathlib import Path

from .config import RAIZ

LOCAL = RAIZ / "entregas_vps"


def _r2():
    nomes = ("FABRICA_R2_ENDPOINT", "FABRICA_R2_BUCKET", "FABRICA_R2_ACCESS_KEY", "FABRICA_R2_SECRET_KEY")
    valores = [os.environ.get(n, "").strip() for n in nomes]
    return valores if all(valores) else None


def na_nuvem() -> bool:
    return _r2() is not None


def _cliente():
    import boto3
    from botocore.config import Config

    endpoint, _, chave, segredo = _r2()
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=chave, aws_secret_access_key=segredo,
                        region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 5}))


def guardar(arquivo: Path, objeto: str) -> str:
    """Sobe o arquivo e devolve a chave dele (objeto)."""
    if na_nuvem():
        _, balde, _, _ = _r2()
        _cliente().upload_file(str(arquivo), balde, objeto, ExtraArgs={"ContentType": "video/mp4"})
        return objeto
    destino = LOCAL / objeto
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(arquivo, destino)
    return objeto


def link(objeto: str, segundos: int, nome_do_arquivo: str = "video.mp4") -> str:
    """O endereço para baixar, válido por `segundos` (no R2). No modo local, None: a API serve o arquivo."""
    if not objeto or not na_nuvem():
        return None
    _, balde, _, _ = _r2()
    segundos = max(60, min(int(segundos), 7 * 24 * 3600))
    return _cliente().generate_presigned_url(
        "get_object", Params={"Bucket": balde, "Key": objeto,
                              "ResponseContentDisposition": f'attachment; filename="{nome_do_arquivo}"'},
        ExpiresIn=segundos)


def caminho_local(objeto: str):
    caminho = (LOCAL / objeto).resolve()
    if LOCAL.resolve() not in caminho.parents or not caminho.exists():
        return None
    return caminho


def apagar(objeto: str) -> None:
    if not objeto:
        return
    if na_nuvem():
        _, balde, _, _ = _r2()
        _cliente().delete_object(Bucket=balde, Key=objeto)
        return
    caminho = caminho_local(objeto)
    if caminho is not None:
        caminho.unlink(missing_ok=True)
