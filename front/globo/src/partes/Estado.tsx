import { CircleAlert, Info } from "lucide-react"
import type { ReactNode } from "react"

/** Carregando, vazio e erro, desenhados do mesmo jeito em todas as telas (guia, item 1.8). */
export function Estado({ tipo, titulo, children }: { tipo: "carregando" | "vazio" | "erro"; titulo: string; children?: ReactNode }) {
  return (
    <div className={tipo === "carregando" ? "estado" : "aviso"} role={tipo === "erro" ? "alert" : "status"}>
      {tipo === "carregando" ? (
        <span className="girando" aria-hidden="true" />
      ) : tipo === "erro" ? (
        <CircleAlert size={20} aria-hidden="true" />
      ) : (
        <Info size={20} aria-hidden="true" />
      )}
      <div>
        <strong>{titulo}</strong>
        {children}
      </div>
    </div>
  )
}
