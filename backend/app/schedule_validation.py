"""Validate both schedule graphs under the project's mutation lock."""
from fastapi import HTTPException

def has_cycle(graph):
    done=set()
    for root in graph:
        if root in done:
            continue
        active=set()
        stack=[(root,False)]
        while stack:
            node,leaving=stack.pop()
            if leaving:
                active.discard(node);done.add(node);continue
            if node in active:
                return True
            if node in done:
                continue
            active.add(node);stack.append((node,True))
            stack.extend((child,False) for child in graph.get(node,[]) if child in graph)
    return False

def validate_project_links(site,stage_id,parent_id,predecessor_ids):
    from core.models import ConstructionSite,Stage
    ConstructionSite.objects.select_for_update().get(pk=site.pk)
    rows=list(Stage.objects.filter(zone__site=site).select_related("parent").prefetch_related("predecessors"))
    parents={s.external_id:([s.parent.external_id] if s.parent else []) for s in rows}
    dependencies={s.external_id:[p.external_id for p in s.predecessors.all()] for s in rows}
    parents[stage_id]=[parent_id] if parent_id else []
    dependencies[stage_id]=list(predecessor_ids)
    if has_cycle(parents):
        raise HTTPException(400,"Родительская работа создаёт цикл иерархии.")
    if has_cycle(dependencies):
        raise HTTPException(400,"Связи предшествования создают цикл. Измените предшественников.")
