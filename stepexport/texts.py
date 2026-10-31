"""User-facing strings: English (default), French, Spanish. Follows
IngeTrazo's language; any other language falls back to English."""

TEXTS = {
    "en": {
        "title": "STEP / IGES export", "menu": "Export to STEP / IGES…",
        "menu_tip": "Export groups as editable STEP (.stp) or IGES (.igs) solids, with recognised cylinders.",
        "format": "Format", "fmt_step": "STEP (.stp)", "fmt_iges": "IGES, solids (.igs)",
        "fmt_iges_surf": "IGES, surfaces (.igs)",
        "fmt_tip": "IGES solids: one B-rep solid per part (IGES 5.3, entity 186). "
                   "IGES surfaces: one trimmed surface per face, the oldest form, for "
                   "programs that do not read IGES solids; they sew the faces back.",
        "content": "Content", "all": "Whole visible model", "selection": "Selection only",
        "unit": "Unit", "unit_doc": "Document ({u})",
        "unit_tip": "Document: the units set in IngeTrazo (feet and inches go out in inches).",
        "cyl": "Recognise cylinders (V2)",
        "cyl_tip": "Faceted holes, rods, rounds and fillets become true cylinders in the file.",
        "detect": "Detection", "soft": "Soft edges (recommended)",
        "geometry": "Geometry only (angle ≤ 25°)", "colors": "Face colours",
        "author": "Author", "analyse": "Analyse", "export": "Export…",
        "dxf": "Convert a DXF to STEP / IGES…", "dxf_open": "DXF to convert",
        "dxf_show": "Show the result in the model",
        "dxf_show_tip": "After converting, the .stp is read back into the model: you see exactly "
                        "what was written (one group per solid, selected; Ctrl+Z removes them).",
        "dxf_shown": "Result shown in the model: one group per solid, selected (Ctrl+Z to remove).",
        "dxf_tip": "Reads the DXF itself in double precision and writes the STEP: exact sizes, "
                   "one solid per part. The open model is not changed.",
        "dxf_done": "{f} read directly (double precision) in {t:.1f} s; {u}.",
        "dxf_units_declared": "units from the file header",
        "dxf_units_guessed": "no units in the file: taken as {u} from the model size",
        "simplify": "Simplify curved surfaces", "tolerance": "Tolerance",
        "simplify_tip": "Merges neighbouring facets lying within the tolerance of one plane "
                        "(finely sampled curves). The model itself is not changed.",
        "placeholder": "The export report shows here.",
        "nothing": "Nothing to export: empty model, or no group selected.",
        "failed": "Export failed:", "written": "File written:", "dialog": "Export to STEP",
        "dialog_iges": "Export to IGES", "default_iges": "model.igs",
        "default_name": "model.stp", "loose": "Loose geometry",
        # report
        "summary": "{s} solid(s), {o} open surface(s), {f} face(s), {c} cylinder(s)",
        "solid": "solid", "open": "OPEN", "faces": "{n} faces", "instead": " (instead of {n})",
        "rod": "rod", "round": "round", "hole": "hole", "fillet": "fillet",
        "facets": "facets", "kept": "kept as facets",
        # import
        "menu_import": "Import STEP…",
        "menu_import_tip": "Import a STEP (.stp) assembly: one group per part, named and coloured.",
        "import": "Import…", "import_dialog": "Import a STEP file",
        "imported": "{n} part(s) imported from {f} in {t:.1f} s (one undo step).",
        "import_unread": "Not read: {w}.", "import_failed": "Import failed:",
        "import_none": "No solid found in this file.",
    },
    "fr": {
        "title": "Export STEP / IGES", "menu": "Exporter en STEP / IGES…",
        "menu_tip": "Exporte les groupes en solides STEP (.stp) ou IGES (.igs) éditables, avec les cylindres reconnus.",
        "format": "Format", "fmt_step": "STEP (.stp)", "fmt_iges": "IGES, solides (.igs)",
        "fmt_iges_surf": "IGES, surfaces (.igs)",
        "fmt_tip": "IGES solides : un solide B-rep par pièce (IGES 5.3, entité 186). "
                   "IGES surfaces : une surface détourée par face, la forme la plus ancienne, pour "
                   "les logiciels qui ne lisent pas les solides IGES ; ils recousent les faces.",
        "content": "Contenu", "all": "Tout le modèle visible", "selection": "Sélection seulement",
        "unit": "Unité", "unit_doc": "Document ({u})",
        "unit_tip": "Document : les unités réglées dans IngeTrazo (pieds-pouces exportés en pouces).",
        "cyl": "Reconnaître les cylindres (V2)",
        "cyl_tip": "Trous, tiges, arrondis et congés à facettes deviennent de vrais cylindres dans le fichier.",
        "detect": "Repérage", "soft": "Arêtes adoucies (recommandé)",
        "geometry": "Géométrie seule (angle ≤ 25°)", "colors": "Couleurs des faces",
        "author": "Auteur", "analyse": "Analyser", "export": "Exporter…",
        "dxf": "Convertir un DXF en STEP / IGES…", "dxf_open": "DXF à convertir",
        "dxf_show": "Afficher le résultat dans le modèle",
        "dxf_show_tip": "Après la conversion, le .stp est relu dans le modèle : on voit exactement "
                        "ce qui a été écrit (un groupe par solide, sélectionnés ; Ctrl+Z les retire).",
        "dxf_shown": "Résultat affiché dans le modèle : un groupe par solide, sélectionnés (Ctrl+Z pour les retirer).",
        "dxf_tip": "Lit le DXF lui-même en double précision et écrit le STEP : cotes exactes, "
                   "un solide par pièce. Le modèle ouvert n'est pas modifié.",
        "dxf_done": "{f} lu directement (double précision) en {t:.1f} s ; {u}.",
        "dxf_units_declared": "unités lues dans l'en-tête du fichier",
        "dxf_units_guessed": "pas d'unités dans le fichier : {u} d'après la taille du modèle",
        "simplify": "Simplifier les surfaces courbes", "tolerance": "Tolérance",
        "simplify_tip": "Fusionne les facettes voisines qui tiennent dans un même plan à la "
                        "tolérance près (courbes trop finement découpées). Le modèle n'est pas modifié.",
        "placeholder": "Le rapport d'export s'affiche ici.",
        "nothing": "Rien à exporter : modèle vide, ou aucun groupe sélectionné.",
        "failed": "Échec de l'export :", "written": "Fichier écrit :", "dialog": "Exporter en STEP",
        "dialog_iges": "Exporter en IGES", "default_iges": "modele.igs",
        "default_name": "modele.stp", "loose": "Géométrie libre",
        "summary": "{s} solide(s), {o} surface(s) ouverte(s), {f} face(s), {c} cylindre(s)",
        "solid": "solide", "open": "OUVERT", "faces": "{n} faces", "instead": " (au lieu de {n})",
        "rod": "tige", "round": "arrondi", "hole": "trou", "fillet": "congé",
        "facets": "facettes", "kept": "gardé en facettes",
        "menu_import": "Importer un fichier STEP…",
        "menu_import_tip": "Importe un assemblage STEP (.stp) : un groupe par pièce, nommé et coloré.",
        "import": "Importer…", "import_dialog": "Importer un fichier STEP",
        "imported": "{n} pièce(s) importée(s) de {f} en {t:.1f} s (une seule étape d'annulation).",
        "import_unread": "Non lu : {w}.", "import_failed": "Échec de l'import :",
        "import_none": "Aucun solide trouvé dans ce fichier.",
        "reasons": {
            "open border": "bord ouvert", "non-simple border": "contour non simple",
            "open border loop": "contour ouvert",
            "border on a plane almost parallel to the axis":
                "bord sur un plan presque parallèle à l'axe",
            "touches another cylinder": "contact avec un autre cylindre",
            "no seam edge": "pas d'arête de couture",
            "unsupported topology": "topologie non gérée",
            "border without axial line": "contour sans ligne d'axe",
            "open edges": "arêtes ouvertes", "non-manifold edge": "arête non-manifold",
            "inconsistent orientation": "orientation incohérente",
        },
        "notes": {
            "planar hole(s) capped": "trou(s) plan(s) bouché(s)",
            "T-junction(s) stitched": "jonction(s) en T recousue(s)",
            "duplicate face(s) dropped": "face(s) en double supprimée(s)",
            "stray face(s) dropped": "face(s) parasite(s) supprimée(s)",
            "facet(s) merged": "facette(s) fusionnée(s)",
            "non-planar face triangulated": "face non plane triangulée",
            "zero-area face dropped": "face d'aire nulle retirée",
            "holes of a non-planar face were dropped": "trous d'une face non plane ignorés",
        },
    },
    "es": {
        "title": "Exportar STEP / IGES", "menu": "Exportar a STEP / IGES…",
        "menu_tip": "Exporta los grupos como sólidos STEP (.stp) o IGES (.igs) editables, con los cilindros reconocidos.",
        "format": "Formato", "fmt_step": "STEP (.stp)", "fmt_iges": "IGES, sólidos (.igs)",
        "fmt_iges_surf": "IGES, superficies (.igs)",
        "fmt_tip": "IGES sólidos: un sólido B-rep por pieza (IGES 5.3, entidad 186). "
                   "IGES superficies: una superficie recortada por cara, la forma más antigua, para "
                   "los programas que no leen sólidos IGES; ellos vuelven a coser las caras.",
        "content": "Contenido", "all": "Todo el modelo visible", "selection": "Solo la selección",
        "unit": "Unidad", "unit_doc": "Documento ({u})",
        "unit_tip": "Documento: las unidades ajustadas en IngeTrazo (pies y pulgadas se exportan en pulgadas).",
        "cyl": "Reconocer cilindros (V2)",
        "cyl_tip": "Agujeros, varillas, redondeos y empalmes facetados pasan a ser cilindros reales en el archivo.",
        "detect": "Detección", "soft": "Aristas suavizadas (recomendado)",
        "geometry": "Solo geometría (ángulo ≤ 25°)", "colors": "Colores de las caras",
        "author": "Autor", "analyse": "Analizar", "export": "Exportar…",
        "dxf": "Convertir un DXF a STEP / IGES…", "dxf_open": "DXF a convertir",
        "dxf_show": "Mostrar el resultado en el modelo",
        "dxf_show_tip": "Tras la conversión, el .stp se vuelve a leer en el modelo: se ve exactamente "
                        "lo que se escribió (un grupo por sólido, seleccionados; Ctrl+Z los quita).",
        "dxf_shown": "Resultado mostrado en el modelo: un grupo por sólido, seleccionados (Ctrl+Z para quitarlos).",
        "dxf_tip": "Lee el propio DXF en doble precisión y escribe el STEP: cotas exactas, "
                   "un sólido por pieza. El modelo abierto no se modifica.",
        "dxf_done": "{f} leído directamente (doble precisión) en {t:.1f} s; {u}.",
        "dxf_units_declared": "unidades leídas en la cabecera del archivo",
        "dxf_units_guessed": "el archivo no tiene unidades: {u} según el tamaño del modelo",
        "simplify": "Simplificar las superficies curvas", "tolerance": "Tolerancia",
        "simplify_tip": "Une las facetas vecinas que caben en un mismo plano dentro de la "
                        "tolerancia (curvas divididas en exceso). El modelo no se modifica.",
        "placeholder": "Aquí aparece el informe de exportación.",
        "nothing": "Nada que exportar: modelo vacío o ningún grupo seleccionado.",
        "failed": "Error en la exportación:", "written": "Archivo escrito:", "dialog": "Exportar a STEP",
        "dialog_iges": "Exportar a IGES", "default_iges": "modelo.igs",
        "default_name": "modelo.stp", "loose": "Geometría suelta",
        "summary": "{s} sólido(s), {o} superficie(s) abierta(s), {f} cara(s), {c} cilindro(s)",
        "solid": "sólido", "open": "ABIERTO", "faces": "{n} caras", "instead": " (en lugar de {n})",
        "rod": "varilla", "round": "redondeo", "hole": "agujero", "fillet": "empalme",
        "facets": "facetas", "kept": "conservado en facetas",
        "menu_import": "Importar un archivo STEP…",
        "menu_import_tip": "Importa un ensamblaje STEP (.stp): un grupo por pieza, con nombre y color.",
        "import": "Importar…", "import_dialog": "Importar un archivo STEP",
        "imported": "{n} pieza(s) importada(s) de {f} en {t:.1f} s (un solo paso de deshacer).",
        "import_unread": "No leído: {w}.", "import_failed": "Error en la importación:",
        "import_none": "No se encontró ningún sólido en este archivo.",
        "reasons": {
            "open border": "borde abierto", "non-simple border": "contorno no simple",
            "open border loop": "contorno abierto",
            "border on a plane almost parallel to the axis":
                "borde en un plano casi paralelo al eje",
            "touches another cylinder": "toca otro cilindro",
            "no seam edge": "sin arista de costura",
            "unsupported topology": "topología no admitida",
            "border without axial line": "contorno sin línea axial",
            "open edges": "aristas abiertas", "non-manifold edge": "arista no-manifold",
            "inconsistent orientation": "orientación incoherente",
        },
        "notes": {
            "planar hole(s) capped": "agujero(s) plano(s) tapado(s)",
            "T-junction(s) stitched": "unión(es) en T cosida(s)",
            "duplicate face(s) dropped": "cara(s) duplicada(s) eliminada(s)",
            "stray face(s) dropped": "cara(s) sobrante(s) eliminada(s)",
            "facet(s) merged": "faceta(s) unida(s)",
            "non-planar face triangulated": "cara no plana triangulada",
            "zero-area face dropped": "cara de área nula eliminada",
            "holes of a non-planar face were dropped": "agujeros de una cara no plana ignorados",
        },
    },
}


def language():
    try:                                     # inside IngeTrazo
        from core.i18n import current_language
        lang = current_language() or "en"
    except Exception:
        lang = "en"
    lang = lang.lower().replace("_", "-").split("-", 1)[0]   # es-MX -> es
    return lang if lang in TEXTS else "en"


def texts(lang=None):
    return TEXTS.get(lang or language(), TEXTS["en"])
