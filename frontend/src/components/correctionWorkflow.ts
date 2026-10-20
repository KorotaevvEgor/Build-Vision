import type {CorrectionStatus} from '../api';
const moves:Record<CorrectionStatus,CorrectionStatus[]>={todo:['in_progress'],in_progress:['todo','ready'],ready:['todo','in_progress'],training:[],trained:['in_progress']};
export function correctionMoveIntent(from:CorrectionStatus,to:CorrectionStatus,canTrain:boolean):'move'|'train'|'forbidden'{
 if(from==='training')return 'forbidden';
 if(from===to)return 'move';
 if(from==='ready'&&to==='training'&&canTrain)return 'train';
 return moves[from].includes(to)?'move':'forbidden';
}
