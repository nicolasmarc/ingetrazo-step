"""User-facing strings (English default, French). Follows IngeTrazo's
language when it is French; any other language falls back to English."""

TEXTS = {
    "en": {
        "title": "STEP export", "menu": "Export to STEP…",
        "menu_tip": "Export groups as editable STEP (.stp) solids, with recognised cylinders.",
        "content": "Content", "all": "Whole visible model", "selection": "Selection only",
        "unit": "Unit", "cyl": "Recognise cylinders (V2)",
        "cyl_tip": "Faceted holes, rods, rounds and fillets become true cylinders in the file.",
        "detect": "Detection", "soft": "Soft edges (recommended)",
        "geometry": "Geometry only (angle ≤ 20°)", "colors": "Face colours",
        "author": "Author", "analyse": "Analyse", "export": "Export…",
        "simplify": "Simplify curved surfaces", "tolerance": "Tolerance",
        "simplify_tip": "Merges neighbouring facets lying within the tolerance of one plane "
                        "(finely sampled curves). The model itself is not changed.",
        "placeholder": "The export report shows here.",
        "nothing": "Nothing to export: empty model, or no group selected.",
        "failed": "Export failed:", "written": "File written:", "dialog": "Export to STEP",
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
        "title": "Export STEP", "menu": "Exporter en STEP…",
        "menu_tip": "Exporte les groupes en solides STEP (.stp) éditables, avec les cylindres reconnus.",
        "content": "Contenu", "all": "Tout le modèle visible", "selection": "Sélection seulement",
        "unit": "Unité", "cyl": "Reconnaître les cylindres (V2)",
        "cyl_tip": "Trous, tiges, arrondis et congés à facettes deviennent de vrais cylindres dans le fichier.",
        "detect": "Repérage", "soft": "Arêtes adoucies (recommandé)",
        "geometry": "Géométrie seule (angle ≤ 20°)", "colors": "Couleurs des faces",
        "author": "Auteur", "analyse": "Analyser", "export": "Exporter…",
        "simplify": "Simplifier les surfaces courbes", "tolerance": "Tolérance",
        "simplify_tip": "Fusionne les facettes voisines qui tiennent dans un même plan à la "
                        "tolérance près (courbes trop finement découpées). Le modèle n'est pas modifié.",
        "placeholder": "Le rapport d'export s'affiche ici.",
        "nothing": "Rien à exporter : modèle vide, ou aucun groupe sélectionné.",
        "failed": "Échec de l'export :", "written": "Fichier écrit :", "dialog": "Exporter en STEP",
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
            "oblique border (cut not perpendicular to the axis)":
                "bord oblique (coupe non perpendiculaire à l'axe)",
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
}


def language():
    try:                                     # inside IngeTrazo
        from core.i18n import current_language
        lang = current_language()
    except Exception:
        lang = "en"
    return lang if lang in TEXTS else "en"


def texts(lang=None):
    return TEXTS.get(lang or language(), TEXTS["en"])
