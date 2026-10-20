"""Independent, comparable visual observations. No automatic engineering closure."""
import os

MIN_INTERVAL_SECONDS = max(1, int(os.environ.get('SK_PROOF_MIN_INTERVAL_SECONDS','600')))
MAX_INTERVAL_SECONDS = max(MIN_INTERVAL_SECONDS, int(os.environ.get('SK_PROOF_MAX_INTERVAL_SECONDS','5400')))
MIN_FRAMES = max(2, int(os.environ.get('SK_PROOF_MIN_FRAMES','2')))

def record_evidence(deviation, observation, *, present, observation_status):
    from core.models import DeviationEvidence
    existing=DeviationEvidence.objects.filter(deviation=deviation,observation=observation).first()
    if existing:
        return existing
    evaluation=observation.stage_evaluations.filter(stage_id=deviation.stage_id).first() if deviation.stage_id else None
    snapshot=evaluation.methodology_snapshot if evaluation else {}
    fingerprint=snapshot.get('rule_fingerprint','')
    outcome='finding' if present else 'clear'
    reason='Независимое наблюдение с подтверждённым временем и неизменным правилом'
    accepted=True
    rows=DeviationEvidence.objects.filter(deviation=deviation).select_related('observation').order_by('pk')
    baseline=rows.filter(independent=True).first()
    previous=rows.exclude(reason__startswith='Повтор файла').last()
    if not observation.date_confirmed or not observation.captured_at:
        accepted=False;reason='Не подтверждено точное время съёмки; серия не доказана'
    elif not observation.camera_id:
        accepted=False;reason='Не указана камера наблюдения'
    elif not snapshot.get('coverage_verified') or not fingerprint:
        accepted=False;reason='Нет сохранённой версии правила и проверяемого рабочего участка'
    elif not evaluation or evaluation.status=='insufficient_data':
        accepted=False;reason='Наблюдение недостаточно для проверки этой работы'
    elif not present and evaluation.status!='no_deviation':
        accepted=False;reason='Этот снимок не опровергает отклонение по работе'
    elif rows.filter(observation__image_sha256=observation.image_sha256).exists():
        accepted=False;reason='Повтор файла: контрольная сумма уже есть в доказательствах'
    elif baseline and (baseline.observation.camera_id!=observation.camera_id or baseline.rule_fingerprint!=fingerprint):
        accepted=False;reason='Изменилась камера, правило или геометрия рабочего участка; нужна отдельная проверка'
    else:
        last=rows.filter(independent=True).last()
        if last and (observation.captured_at-last.observation.captured_at).total_seconds()<MIN_INTERVAL_SECONDS:
            accepted=False;reason='Время съёмки не позже предыдущего либо интервал слишком мал'
    sequence=1 if accepted else 0
    if accepted and previous and previous.independent and previous.outcome==outcome:
        seconds=(observation.captured_at-previous.observation.captured_at).total_seconds()
        if MIN_INTERVAL_SECONDS<=seconds<=MAX_INTERVAL_SECONDS:
            sequence=previous.sequence_count+1
        else:
            reason='Независимый кадр; разрыв серии превышает профиль подтверждения'
    return DeviationEvidence.objects.create(deviation=deviation,observation=observation,outcome=outcome if accepted else 'inconclusive',
        independent=accepted,sequence_count=sequence,reason=reason,rule_fingerprint=fingerprint,methodology_snapshot=snapshot)

def proof_summary(item):
    records=sorted(item.evidence_records.all(),key=lambda r:r.pk,reverse=True)
    latest=records[0] if records else None
    accepted=next((r for r in records if r.independent),None)
    level='legacy_unverified';label='Историческая фиксация — серия не проверена'
    if accepted:
        level='single_observation';label='Одно независимое наблюдение'
        if accepted.outcome=='clear':
            level='not_reproduced';label='На контрольном наблюдении не воспроизвелось'
        elif accepted.sequence_count>=MIN_FRAMES:
            level='repeated_observation';label='Расхождение повторяется на независимых снимках'
    if latest and not latest.independent and not latest.reason.startswith('Повтор файла'):
        level='needs_review';label='Сопоставимость последнего наблюдения требует проверки'
    return {'level':level,'label':label,'independent_count':sum(r.independent for r in records),
        'sequence_count':accepted.sequence_count if accepted else 0,'reason':latest.reason if latest else 'Старые счётчики не заменяют проверку независимости снимков',
        'profile':{'min_frames':MIN_FRAMES,'min_interval_seconds':MIN_INTERVAL_SECONDS,'max_interval_seconds':MAX_INTERVAL_SECONDS},
        'records':[{'observation_id':str(r.observation_id),'outcome':r.outcome,'independent':r.independent,
            'sequence_count':r.sequence_count,'reason':r.reason,'rule_fingerprint':r.rule_fingerprint,
            'captured_at':r.observation.captured_at.isoformat() if r.observation.captured_at else None} for r in records[:30]]}
