from datetime import date
from app.matching import evaluate_observation
from test_matching_rules import stage, det, rules, KOTLOVAN_RULE_WITH_QUANTITIES
from app.schedule import Schedule

def evaluate(detections, zones):
    return evaluate_observation(zone_id='zone-a', observed_date=date(2026,9,15),
        date_confirmed=True, detections=detections,
        schedule=Schedule(is_demo=True, stages=[stage('stage-kotlovan')]),
        rules=rules({'stage-kotlovan':KOTLOVAN_RULE_WITH_QUANTITIES}), frame_zones=zones).stage_evaluations[0]

def test_parking_is_visible_but_not_counted_for_work():
    truck=det('dump_truck');truck.frame_zone_kind='parking';truck.frame_zone_id=2
    result=evaluate([det('excavator'),truck],[{'id':1,'kind':'work','stage_id':None}])
    check=next(c for c in result.quantity_checks if c.class_key=='dump_truck')
    assert check.actual_qty==0 and check.observed_qty==1 and check.excluded_qty==1
    assert result.methodology['rule_fingerprint']

def test_missing_work_coverage_cannot_prove_missing_machine():
    result=evaluate([],[])
    assert result.status=='insufficient_data'
    assert not result.methodology['coverage_verified']

def test_rule_change_changes_saved_fingerprint():
    result=evaluate([], [{'id':1,'kind':'work','stage_id':None,'polygon':[[0,0],[1,1],[0,1]]}])
    changed=evaluate([], [{'id':1,'kind':'work','stage_id':None,'polygon':[[0,0],[2,2],[0,1]]}])
    assert result.methodology['rule_fingerprint']!=changed.methodology['rule_fingerprint']


def test_frame_telemetry_does_not_change_temporal_rule_identity():
    from app.matching_evidence import select_work_detections
    def snapshot(context):
        return select_work_detections(stage('stage-kotlovan'), KOTLOVAN_RULE_WITH_QUANTITIES,
            [], [], set(), context)[1]
    stable = {'weights': 'world.pt', 'confidence': .3, 'correction_version': 5,
              'class_thresholds': {'dump_truck': .4}}
    first_trace = {'run_id': 'frame-1', 'detector': {'detection_count': 2},
                   'correction': {'classified_count': 1, 'changed_count': 0}}
    second_trace = {'run_id': 'frame-2', 'detector': {'detection_count': 7},
                    'correction': {'classified_count': 3, 'changed_count': 2}}
    first = snapshot({**stable, 'execution': first_trace})
    second = snapshot({**stable, 'execution': second_trace})
    assert first['rule_fingerprint'] == second['rule_fingerprint']
    assert first['rule']['detector']['execution'] == first_trace
    assert second['rule']['detector']['execution'] == second_trace
    for key, value in [('weights', 'new.pt'), ('confidence', .5), ('correction_version', 6),
                       ('class_thresholds', {'dump_truck': .6})]:
        assert snapshot({**stable, key: value, 'execution': first_trace})['rule_fingerprint'] != first['rule_fingerprint']
