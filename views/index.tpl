<!DOCTYPE html>
<html lang="en">
<head>

 <title>Kiln Controller</title>
 <meta name="viewport" content="width=device-width, initial-scale=1.0">

 <script src="/assets/js/jquery-1.10.2.min.js"></script>
 <script src="/assets/js/jquery.event.drag-2.2.js"></script>
 <script src="/assets/js/jquery.flot.js"></script>
 <script src="/assets/js/jquery.flot.resize.js"></script>
 <script src="/assets/js/jquery.flot.draggable.js"></script>
 <script src="/assets/js/bootstrap.min.js"></script>
 <script src="/assets/js/jquery.bootstrap-growl.min.js"></script>
 <script src="/assets/js/select2.min.js"></script>
 <script src="/assets/js/ui.js"></script>

 <link rel="stylesheet" href="/assets/css/bootstrap.min.css"/>
 <link rel="stylesheet" href="/assets/css/bootstrap-theme.min.css"/>
 <link rel="stylesheet" href="/assets/css/bootstrap-modal.css"/>
 <link rel="stylesheet" href="/assets/css/select2.css"/>
 <link rel="stylesheet" href="/assets/css/ui.css"/>

</head>
<body>

 <div class="container">
  <div id="status">
   <div class="ds-title-panel">
    <div class="ds-title">Sensor Temp</div>
    <div class="ds-title">Target Temp</div>
    <div class="ds-title">Heat Rate</div>
    <div class="ds-title">Cost</div>
    <div class="ds-title ds-state pull-right" style="border-left: 1px solid #ccc;">Status</div>
   </div>
   <div class="clearfix"></div>
   <div class="ds-panel">
    <div class="display ds-num"><span id="act_temp">25</span><span class="ds-unit" id="act_temp_scale" >&deg;C</span></div>
    <div class="display ds-num ds-target"><span id="target_temp">---</span><span class="ds-unit" id="target_temp_scale">&deg;C</span></div>
    <div class="display ds-num ds-heat-rate"><span id="heat_rate">---</span><span class="ds-unit" id="heat_rate_temp_scale">&deg;C</span></div>
    <div class="display ds-num ds-cost"><span id="cost_value">0.00</span><span class="ds-unit" id="cost_unit"></span></div>
    <div class="display ds-num ds-text" id="state"></div>
    <div class="display pull-right ds-state" style="padding-right:0"><span class="ds-led" id="heat" title="Heating active" data-toggle="tooltip">&#92;</span><span class="ds-led" id="cool" title="Cooling active (placeholder)" data-toggle="tooltip">&#108;</span><span class="ds-led" id="air" title="Air circulation active (placeholder)" data-toggle="tooltip">&#91;</span><span class="ds-led" id="hazard" title="Overheat warning" data-toggle="tooltip">&#73;</span><span class="ds-led" id="door" title="Door open/unknown (placeholder)" data-toggle="tooltip">&#9832;</span></div>
   </div>
   <div class="clearfix"></div>
   <div>
    <div class="progress progress-striped active">
     <div id="progressBar" class="progress-bar"  role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" style="width: 0%">
      <span class="sr-only"></span>
     </div>
    </div>
   </div>
  </div>
  <div class="panel panel-default">
   <div class="panel-heading">
    <div id="profile_selector" class="pull-left">
     <select id="e2" class="select2" style="margin-top: 4px"></select>
     <button id="btn_edit" type="button" class="btn btn-default" onclick="enterEditMode()" title="Edit selected profile" data-toggle="tooltip"><span class="glyphicon glyphicon-edit"></span></button>
     <button id="btn_new" type="button" class="btn btn-default" onclick="enterNewMode(selected_profile)" title="Create new profile" data-toggle="tooltip"><span class="glyphicon glyphicon-plus"></span></button>
    </div>
   <div id="btn_controls" class="pull-right" style="margin-top: 3px">
    <div id="nav_start" class="btn-group" style="display:none">
     <button type="button" class="btn btn-default" style="visibility: hidden;"  onclick="runTaskSimulation();" title="Simulate run" data-toggle="tooltip">Simulate</button>
     <button type="button" class="btn btn-success" data-toggle="modal" data-target="#jobSummaryModal" title="Start selected profile" data-toggle="tooltip"><span class="glyphicon glyphicon-play"></span> Start</button>
    </div>
    <button id="nav_shutdown" type="button" class="btn btn-warning" onclick="shutdownTask()" style="display:none" title="Shut down controller" data-toggle="tooltip"><span class="glyphicon glyphicon-off"></span> Shutdown</button>
    <button id="nav_stop" type="button" class="btn btn-danger" onclick="abortTask()" style="display:none" title="Stop current run" data-toggle="tooltip"><span class="glyphicon glyphicon-stop"></span> Stop</button>
   </div>
    <div id="edit" style="display:none;">
     <div class="input-group">
      <span class="input-group-addon">Schedule Name</span>
      <input id="form_profile_name" type="text" class="form-control" />
      <span class="input-group-btn">
        <button class="btn btn-success" type="button" onclick="saveProfile();" title="Save profile" data-toggle="tooltip">Save</button>
        <button id="btn_exit" type="button" class="btn btn-default" onclick="leaveEditMode()" title="Exit editor" data-toggle="tooltip"><span class="glyphicon glyphicon-remove"></span></button>
      </span>
     </div>
     <div class="btn-group btn-group-sm" style="margin-top: 10px">
      <button id="btn_newPoint" type="button" class="btn btn-default" onclick="newPoint()" title="Add schedule point" data-toggle="tooltip"><span class="glyphicon glyphicon-plus"></span></button>
      <button id="btn_delPoint" type="button" class="btn btn-default" onclick="delPoint()" title="Remove last schedule point" data-toggle="tooltip"><span class="glyphicon glyphicon-minus"></span></button>
     </div>
     <div class="btn-group btn-group-sm" style="margin-top: 10px">
      <button id="btn_table" type="button" class="btn btn-default" onclick="toggleTable()" title="Toggle schedule table" data-toggle="tooltip"><span class="glyphicon glyphicon-list"></span></button>
      <button id="btn_live" type="button" class="btn btn-default" onclick="toggleLive()" title="Toggle live view" data-toggle="tooltip"><span class="glyphicon glyphicon-eye-open"></span></button>
     </div>
     <div class="btn-group btn-group-sm" style="margin-top: 10px">
      <button id="btn_delProfile" type="button" class="btn btn-danger" data-toggle="modal" data-target="#delProfileModal" title="Delete selected profile" data-toggle="tooltip"><span class="glyphicon glyphicon-trash"></span></button>
     </div>
    </div>
   </div>
   <div class="panel-body">
   <div id="graph_container" class="graph"></div>
    <div id="history_controls" class="clearfix" style="margin-top: 10px;">
     <div class="btn-group">
      <button id="btn_live_view" type="button" class="btn btn-primary" onclick="setHistoryMode(false)" title="Show live run data" data-toggle="tooltip">Live</button>
      <button id="btn_history_view" type="button" class="btn btn-default" onclick="setHistoryMode(true)" title="Compare past firings" data-toggle="tooltip">History</button>
     </div>
     <div id="history_picker" class="pull-right" style="display:none">
      <select id="history_select" class="select2" style="width: 260px"></select>
      <button type="button" class="btn btn-default" onclick="addSelectedHistoryRun()" title="Add selected firing to the chart" data-toggle="tooltip"><span class="glyphicon glyphicon-plus"></span></button>
      <button type="button" class="btn btn-default" onclick="clearHistoryRuns()" title="Clear all history runs" data-toggle="tooltip"><span class="glyphicon glyphicon-trash"></span></button>
     </div>
    </div>
  </div>
   <div id="profile_table" class="panel-footer" style="display:none;"></div>
  </div>
 </div>

 <div id="jobSummaryModal" class="modal fade" tabindex="-1" aria-hidden="true" style="display: none;">
  <div class="modal-dialog">
   <div class="modal-content">
    <div class="modal-header">
     <button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
     <h3 class="modal-title" id="jobSummaryModalLabel">Task Overview</h3>
    </div>
    <div class="modal-body">
     <table class="table table-bordered">
      <tr><td>Selected Profile</td><td><b><span id="sel_prof"></span></b></td></tr>
      <tr><td>Estimated Runtime</td><td><b><span id="sel_prof_eta"></span></b></td></tr>
      <tr><td>Estimated Power consumption</td><td><b><span id="sel_prof_cost"></span></b></td></tr>
     </table>
    </div>
    <div class="modal-footer">
     <div class="btn-group" style="width: 100%">
      <button type="button" class="btn btn-danger" style="width: 50%" data-dismiss="modal">No, take me back</button>
      <button type="button" class="btn btn-success" style="width: 50%" data-dismiss="modal" onclick="runTask()">Yes, start the Run</button>
     </div>
    </div>
   </div>
  </div>
 </div>

 <div id="delProfileModal" class="modal fade" tabindex="-1" aria-hidden="true" style="display: none;">
  <div class="modal-dialog">
   <div class="modal-content">
    <div class="modal-header">
     <button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
     <h3 class="modal-title" id="delProfileModalLabel">Delete this profile?</h3>
    </div>
    <div class="modal-body">
     Do your really want to delete this profile?
    </div>
    <div class="modal-footer">
     <div class="btn-group" style="width: 100%">
      <button type="button" class="btn btn-danger" style="width: 50%" data-dismiss="modal">No, take me back</button>
      <button type="button" class="btn btn-success" style="width: 50%" data-dismiss="modal" onclick="deleteProfile()">Yes, delete the profile</button>
     </div>
    </div>
   </div>
  </div>
 </div>

 <div id="overwriteProfileModal" class="modal fade" tabindex="-1" aria-hidden="true" style="display: none;">
  <div class="modal-dialog">
   <div class="modal-content">
    <div class="modal-header">
     <button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
     <h3 class="modal-title" id="overwriteProfileModalLabel">Overwrite this profile?</h3>
    </div>
    <div class="modal-body">
     Do your really want to overwrite this profile?
    </div>
    <div class="modal-footer">
     <div class="btn-group" style="width: 100%">
      <button type="button" class="btn btn-danger" style="width: 50%" data-dismiss="modal">No, take me back</button>
      <button type="button" class="btn btn-success" style="width: 50%" data-dismiss="modal" onclick="deleteProfile()">Yes, delete the profile</button>
     </div>
    </div>
   </div>
  </div>
 </div>

</body>
</html>
