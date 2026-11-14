import type { HTMLAttributes } from "react"

type Parte = string | number | null | undefined

type Props = Omit<HTMLAttributes<HTMLSpanElement>, "className"> & {
  /** Partes vindas dos dados; nulos não inventam uma medida. O separador fica no rótulo mono. */
  partes?: readonly Parte[]
}

/** Rótulo mono V2. Mantém o ponto médio restrito a este elemento, sem formatação global de textos. */
export function RotuloMono({ partes, children, ...atributos }: Props) {
  return <span {...atributos} className="rot">{partes ? partes.filter((parte) => parte !== null && parte !== undefined && parte !== "").join(" · ") : children}</span>
}
