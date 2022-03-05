/* Controlling tradfri */

// Light on/off
$('#tradfri-commands .light-state').on('click', e => {
  let element = e.currentTarget;
  let groupID = $(element).closest('.tradfri-container').attr('group-id');
  let endpoint = isOnCurrently ? 'off' : 'on';

  sendTradfriOnOff(groupID, endpoint, () => {
    isOnCurrently ? element.classList.remove('on') : element.classList.add('on');
  });
});

// Dim change
$('#tradfri-commands .slider').on('change', e => {
  let element = e.currentTarget;
  let groupID = $(element).closest('.tradfri-container').attr('group-id');

  sendTradfriDimmer(groupID, element.value);
});

// Color change
$('#tradfri-commands .hex-suggestion').on('click', e => {
  let $element = $(e.currentTarget);
  let groupID = $element.closest('.tradfri-container').attr('group-id');

  sendTradfriColor(groupID, $element.attr('value'));
});


/* Scheduling tradfri */

// Light on/off
$(document).on('click', '.event-commands-edit-container .light-state:not([disabled])', e => {
  let element = e.currentTarget;
  let $element = $(element);
  let isOnCurrently = element.classList.contains('on');
  $element.next('input.hidden').prop('checked', !isOnCurrently);
  let $container = $element.closest('.tradfri-container');
  if (isOnCurrently) {
    element.classList.remove('on');
    $container.find('.dimmer-container input').attr('disabled', true);
    $container.find('.hex-container input').attr('disabled', true);
  } else {
    element.classList.add('on');
    $container.find('.dimmer-container input').removeAttr('disabled');
    $container.find('.hex-container input').removeAttr('disabled');
  }
});

// Enable/disable this group
$(document).on('click', '.event-commands-edit-container .group-active', e => {
  let $input = $(e.currentTarget);
  let $container = $input.closest('.subgroup');
  let $innerContainer = $container.find('.tradfri-inner-container');
  let $childInputs = $innerContainer.find('input').not($input);

  if ($input.prop('checked')) {
    $innerContainer.removeClass('inactive');
    $innerContainer.find('.light-state').removeAttr('disabled');
    if ($innerContainer.find('[key="light-state"]').prop('checked')) {
      $childInputs.removeAttr('disabled');
    }
  } else {
    $childInputs.attr('disabled', "true");
    $innerContainer.addClass('inactive');
    $innerContainer.find('.light-state').attr('disabled', true);
  }
});

// Select color
$(document).on('click', '.event-commands-edit-container .hex-suggestion', e => {
  let $input = $(e.currentTarget);
  $input.prop('checked', true);
  $input.attr('checked', true);

  $input.next('.checkmark').show();

  // Disable every other input
  $container = $input.closest('.hex-container');
  $container.find('.hex-suggestion').not($input).each((_, e) => {
    $siblingInput = $(e);
    $siblingInput.prop('checked', false);
    $siblingInput.removeAttr('checked');
    $siblingInput.next('.checkmark').hide();
  });
});

// Deselect color
$(document).on('click', '.hex-container .checkmark', e => {
  $element = $(e.currentTarget);
  $element.hide();

  $input = $element.prev('input');
  $input.prop('checked', false);
  $input.removeAttr('checked');
});
