"""Reproducible work-scoped selection; frame presence is not resource allocation."""
import hashlib
import json

METHOD_VERSION = 'work-zones-v2'

def select_work_detections(stage, rule, detections, frame_zones, shared_classes, analysis_context=None):
    zones = frame_zones or []
    work = [z for z in zones if z.get('kind') == 'work' and z.get('stage_id') in (None, stage.stage_id)]
    by_id = {z['id']: z for z in zones}
    selected, excluded = [], []
    allocation_unknown = False
    for index, detection in enumerate(detections):
        zone = by_id.get(detection.frame_zone_id)
        reason = ''
        if frame_zones is not None:
            if not zone:
                reason = 'Вне размеченного рабочего участка'
            elif zone.get('kind') != 'work':
                reason = 'Отстой, въезд, опасная или неконтролируемая зона'
            elif zone.get('stage_id') not in (None, stage.stage_id):
                reason = 'Участок другой работы'
            elif not zone.get('stage_id') and detection.class_key in shared_classes:
                reason = 'Общий участок параллельных работ: назначение ресурса не определено'
                allocation_unknown = True
        elif detection.frame_zone_kind in {'parking','entrance','danger','uncontrolled'}:
            reason = 'Техника вне рабочего участка'
        if reason:
            excluded.append({'index':index,'class_key':detection.class_key,'label_ru':detection.label_ru,
                             'bbox':detection.bbox,'reason':reason})
        else:
            selected.append(detection)
    context = {'method_version':METHOD_VERSION,'stage_id':stage.stage_id,'zone_id':stage.zone_id,
               'start':stage.start_date.isoformat(),'end':stage.end_date.isoformat(),
               'required':rule.required,'quantities':rule.required_quantities,'allowed':rule.allowed,
               'basis':rule.alternatives_note or stage.technology_assumption,
               'frame_zones':sorted(zones,key=lambda z:str(z.get('id'))),
               'shared_classes':sorted(shared_classes)}
    context['detector'] = analysis_context or {}
    # Invocation telemetry stays in the saved snapshot, but frame-specific run IDs
    # and result counts must not change the rule identity used by temporal proof.
    fingerprint_context = {**context, 'detector': {
        key: value for key, value in context['detector'].items() if key != 'execution'
    }}
    fingerprint=hashlib.sha256(json.dumps(fingerprint_context,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return selected, {'method_version':METHOD_VERSION,'rule_fingerprint':fingerprint,
                     'coverage_verified':bool(work),'scope':'work_polygon' if frame_zones is not None else 'whole_frame_unverified',
                     'rule':context,'excluded_detections':excluded,
                     'counted_detections':[{'index':i,'class_key':d.class_key,'label_ru':d.label_ru,'bbox':d.bbox,'confidence':d.confidence}
                         for i,d in enumerate(detections) if any(d is s for s in selected) and d.in_taxonomy and not d.ambiguous],
                     'counted_indices':[i for i,d in enumerate(detections) if any(d is s for s in selected)],
                     'allocation_unknown':allocation_unknown}
