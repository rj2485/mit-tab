from django.shortcuts import render_to_response
from django.template import RequestContext
from django.http import Http404,HttpResponse,HttpResponseRedirect
from django.contrib.auth.decorators import permission_required
from django.utils import simplejson
from errors import *
from models import *
from django.shortcuts import redirect
from forms import ResultEntryForm
import tab_logic
import random
import sys
import traceback
import send_texts as texting
import backup

@permission_required('tab.tab_settings.can_change', login_url="/403/")
def swap_judges_in_round(request, src_round, src_judge, dest_round, dest_judge):
    try :
        src_round = Round.objects.get(id=src_round)
        src_judge = Judge.objects.get(id=src_judge)
        dest_round = Round.objects.get(id=dest_round)
        dest_judge = Judge.objects.get(id=dest_judge)
        dest_round.judge = src_judge
        src_round.judge = dest_judge
        dest_round.save()
        src_round.save()
        data = {"success":True}
    except Exception as e:
        print "ARG ", e
        data = {"success":False}
    data = simplejson.dumps(data)
    return HttpResponse(data, mimetype='application/json')

@permission_required('tab.tab_settings.can_change', login_url="/403/")
def swap_teams_in_round(request, src_round, src_team, dest_round, dest_team):
    try :
        src_round = Round.objects.get(id=src_round)
        src_team = Team.objects.get(id=src_team)
        dest_round = Round.objects.get(id=dest_round)
        dest_team = Team.objects.get(id=dest_team)
        if src_round.gov_team == src_team:
            if dest_round.gov_team == dest_team:
                # Swap the two gov teams
                src_round.gov_team = dest_team
                dest_round.gov_team = src_team
            else:
                # Swap src_rounds gov team with 
                # dest_round's opp team
                src_round.gov_team = dest_team
                dest_round.opp_team = src_team
        else:
            if dest_round.gov_team == dest_team:
                # Swap src_rounds opp team with
                # dest_round's gov team
                src_round.opp_team = dest_team
                dest_round.gov_team = src_team
            else:
                # Swap the two opp teams
                src_round.opp_team = dest_team
                dest_round.opp_team = src_team
        dest_round.save()
        src_round.save()
        data = {'success':True}
    except Exception as e:
        print "Unable to swap teams: ", e
        data = {'success':False}
    data = simplejson.dumps(data)
    return HttpResponse(data, mimetype='application/json')


@permission_required('tab.tab_settings.can_change', login_url="/403/")
def pair_round(request):
    current_round = TabSettings.objects.get(key="cur_round")
    next_round = current_round.value 
    if request.method == 'POST':
        try:
            backup.backup_round("round_%i_before_pairing.db" % (next_round))
            tab_logic.pair_round()
            backup.backup_round("round_%i_after_pairing.db" % (next_round))
        except Exception, e:
            traceback.print_exc(file=sys.stdout)
            return render_to_response('error.html', 
                                 {'error_type': "Pair Next Round",
                                  'error_name': "Pairing Round %s" % (current_round.value + 1),
                                  'error_info':"Could not pair next round because of: [%s]" %(e)}, 
                                  context_instance=RequestContext(request))           
        current_round.value = current_round.value + 1
        current_round.save() 
        return view_status(request)
    else:
        #We must check a few things:
        # 1) Have all round results been entered
        # 2) Do the round results make sense
        # 3) Are all Judges Checked In
        check_status = []
        current_round = current_round.value
        title = "Pairing Round %s" % (current_round)
        num_rounds = TabSettings.objects.get(key="tot_rounds").value
        rounds = Round.objects.filter(round_number = current_round-1)
        msg = "All Rounds Entered for Overall Round %s" % (current_round-1)
        if not all(map(lambda r: r.victor != 0, rounds)):
            check_status.append((msg, "No", "Missing rounds from the previous round."))
        else :
            check_status.append((msg, "Yes", "Results for previous round have all been entered."))
        #Put sanity checks here
        # end
        checkins = CheckIn.objects.filter(round_number = current_round)
        checked_in_judges = set([c.judge for c in checkins])
        n_over_two = Team.objects.count() / 2
        msg = "N/2 Judges checked in for Round %s?" % (current_round)
        if len(checked_in_judges) < n_over_two:
            check_status.append((msg, 
                                 "No", 
                                 "Not enough judges checked in. Need %i and only have %i"%(n_over_two,len(checked_in_judges))
                                 ))
        else:
            check_status.append((msg, "Yes", "Have judges"))
        ready_to_pair = "Yes"
        ready_to_pair_alt = "Backend ready to pair!"
        try:
            tab_logic.ready_to_pair(current_round)
        except Exception as e:
            ready_to_pair = "No"
            ready_to_pair_alt = str(e) 
        check_status.append(("Backend Ready to Pair?", ready_to_pair, ready_to_pair_alt))
        
        return render_to_response('pair_round.html',
                                locals(),
                                context_instance=RequestContext(request))
                                
@permission_required('tab.tab_settings.can_change', login_url="/403/")                               
def manual_backup(request):
    try:
        backup.backup_round("manual_backup_round_%i_.db" % (TabSettings.objects.get(key="cur_round").value))
    except:
        traceback.print_exc(file=sys.stdout)
        return render_to_response('error.html',
                                 {'error_type': "Manual Backup",'error_name': "Backups",
                                  'error_info': "Could not backup database. Something is wrong with your AWS setup."},
                                  context_instance=RequestContext(request))
    return render_to_response('thanks.html',
                             {'data_type': "Backing up",
                              'data_name': " database backup to aws "},
                               context_instance=RequestContext(request))
                                
def view_status(request):
    current_round_number = TabSettings.objects.get(key="cur_round").value-1
    return view_round(request, current_round_number)

def view_round(request, round_number):
    valid_pairing, errors, byes = True, [], []
    round_pairing = list(Round.objects.filter(round_number = round_number))
    round_pairing.sort(key=lambda x: (max(tab_logic.tot_wins(x.gov_team), tab_logic.tot_wins(x.opp_team)),
                                      max(tab_logic.tot_speaks(x.gov_team), tab_logic.tot_speaks(x.opp_team))))
    round_pairing.reverse()
    #For the template since we can't pass in something nicer like a hash
    round_info = [[pair]+[None]*8 for pair in round_pairing]
    for pair in round_info:
        pair[1] = tab_logic.tot_wins(pair[0].gov_team)
        pair[2] = tab_logic.tot_speaks(pair[0].gov_team)
        pair[3] = tab_logic.num_govs(pair[0].gov_team)    
        pair[4] = tab_logic.num_opps(pair[0].gov_team)    
        pair[5] = tab_logic.tot_wins(pair[0].opp_team)
        pair[6] = tab_logic.tot_speaks(pair[0].opp_team)
        pair[7] = tab_logic.num_govs(pair[0].opp_team)    
        pair[8] = tab_logic.num_opps(pair[0].opp_team)    
    paired_teams = [team.gov_team for team in round_pairing] + [team.opp_team for team in round_pairing]
    n_over_two = Team.objects.filter(checked_in=True).count() / 2
    valid_pairing = len(round_pairing) >= n_over_two
    for present_team in Team.objects.filter(checked_in=True):
        if not (present_team in paired_teams):
            errors.append("%s was not in the pairing" % (present_team))
            byes.append(present_team) 
    pairing_exists = len(round_pairing) > 0 
    excluded_judges = Judge.objects.exclude(round__round_number = round_number).filter(checkin__round_number = round_number)
    non_checkins = Judge.objects.exclude(round__round_number = round_number).exclude(checkin__round_number = round_number)
    size = max(map(len, [excluded_judges, non_checkins, byes]))
    # The minimum rank you want to warn on
    warning = 5
    
    # A seemingly complex one liner to do a fairly simple thing
    # basically this generates the table that the HTML will display such that the output looks like:
    # [ Byes ][Judges not in round but checked in][Judges not in round but not checked in]
    # [ Team1][             CJudge1              ][                 Judge1               ]
    # [ Team2][             CJudge2              ][                 Judge2               ]
    # [      ][             CJudge3              ][                 Judge3               ]
    # [      ][                                  ][                 Judge4               ]
    excluded_people = zip(*map( lambda x: x+[""]*(size-len(x)), [list(byes), list(excluded_judges), list(non_checkins)])) 
    return render_to_response('display_info.html',
                               locals(),
                               context_instance=RequestContext(request))
                               
@permission_required('tab.tab_settings.can_change', login_url="/403/")                               
def send_texts(request):
    try:
        print "#"*80
        print "Sending Texts"   
        print "#"*80
        texting.text()
        print "done sending "
        print "#"*80
    except:
        traceback.print_exc(file=sys.stdout)
        return render_to_response('error.html',
                                 {'error_type': "Texting",'error_name': "Texts",
                                  'error_info': "Could not send texts. Sorry."},
                                  context_instance=RequestContext(request))
    return render_to_response('thanks.html',
                             {'data_type': "Texting",
                              'data_name': "Texts"},
                               context_instance=RequestContext(request))

"""dxiao: added a html page for showing tab for the current round.
Uses view_status and view_round code from revision 108."""
def pretty_pair(request):
    round_number = TabSettings.objects.get(key="cur_round").value-1
    valid_pairing, errors, byes = True, [], []
    round_pairing = list(Round.objects.filter(round_number = round_number))
    #We want a random looking, but constant ordering of the rounds
    random.seed(0xBEEF)
    random.shuffle(round_pairing)
    paired_teams = [team.gov_team for team in round_pairing] + [team.opp_team for team in round_pairing]
    n_over_two = Team.objects.filter(checked_in=True).count() / 2
    valid_pairing = len(round_pairing) >= n_over_two
    for present_team in Team.objects.all():
        if not (present_team in paired_teams):
            errors.append("%s was not in the pairing" % (present_team))
            byes.append(present_team) 
    pairing_exists = len(round_pairing) > 0 
    return render_to_response('round_pairings.html',
                               locals(),
                               context_instance=RequestContext(request))

def view_rounds(request):
    number_of_rounds = TabSettings.objects.get(key="tot_rounds").value
    rounds = [(i, "Round %i" % i) for i in range(1,number_of_rounds+1)]
    return render_to_response('list_data.html',
                              {'item_type':'round',
                               'item_list': rounds,
                               'show_delete': True},
                              context_instance=RequestContext(request))

def enter_result(request, round_id):
    round_obj = Round.objects.get(id=round_id)
    if request.method == 'POST':
        form = ResultEntryForm(request.POST, round_instance=round_obj)
        if form.is_valid():
            try:
                result = form.save()
            except ValueError:
                return render_to_response('error.html', 
                                         {'error_type': "Round Result",
                                          'error_name': "["+str(round_obj)+"]",
                                          'error_info':"Invalid round result, could not remedy."}, 
                                          context_instance=RequestContext(request))
            return render_to_response('thanks.html', 
                                     {'data_type': "Round Result",
                                      'data_name': "["+str(round_obj)+"]"}, 
                                      context_instance=RequestContext(request))
    else:
        is_current = round_obj.round_number == TabSettings.objects.get(key="cur_round")
        form = ResultEntryForm(round_instance=round_obj)
    return render_to_response('data_entry.html', 
                              {'form': form}, 
                               context_instance=RequestContext(request))

@permission_required('tab.tab_settings.can_change', login_url="/403/")
def confirm_start_new_tourny(request):
    return render_to_response('confirm.html', 
                              {'link': "/pairing/start_tourny/",
                               'confirm_text': "Create New Tournament"}, 
                               context_instance=RequestContext(request))
                               
@permission_required('tab.tab_settings.can_change', login_url="/403/")                               
def start_new_tourny(request):
    try:
        clear_db()
        TabSettings.objects.create(key = "cur_round", value = 1)
        TabSettings.objects.create(key = "tot_rounds", value = 5)
        TabSettings.objects.create(key = "var_teams_to_break", value = 8)
        TabSettings.objects.create(key = "nov_teams_to_break", value = 4)

    
    except Exception as e:
        return render_to_response('error.html', 
                            {'error_type': "Could not Start Tournament",
                            'error_name': "",
                            'error_info':"Invalid Tournament State. Time to hand tab. [%s]"%(e)}, 
                            context_instance=RequestContext(request))
    return render_to_response('thanks.html', 
                            {'data_type': "Started New Tournament",
                            'data_name': ""}, 
                            context_instance=RequestContext(request))
        
def clear_db():
    check_ins = CheckIn.objects.all()
    for i in range(len(check_ins)):
        CheckIn.delete(check_ins[i])
    print "Cleared Checkins"
    
    round_stats = RoundStats.objects.all()
    for i in range(len(round_stats)):
        RoundStats.delete(round_stats[i])
    print "Cleared RoundStats"
        
    rounds = Round.objects.all()
    for i in range(len(rounds)):
        Round.delete(rounds[i])
    print "Cleared Rounds"
        
    judges = Judge.objects.all()
    for i in range(len(judges)):
        Judge.delete(judges[i])
    print "Cleared Judges"
        
    rooms = Room.objects.all()
    for i in range(len(rooms)):
        Room.delete(rooms[i])
    print "Cleared Rooms"
        
    scratches = Scratch.objects.all()
    for i in range(len(scratches)):
        Scratch.delete(scratches[i])
    print "Cleared Scratches"
        
    tab_set = TabSettings.objects.all()
    for i in range(len(tab_set)):
        TabSettings.delete(tab_set[i])
    print "Cleared TabSettings"
        
    teams = Team.objects.all()
    for i in range(len(teams)):
        Team.delete(teams[i])   
    print "Cleared Teams"
    
    debaters = Debater.objects.all()
    for i in range(len(debaters)):
        Debater.delete(debaters[i])
    print "Cleared Debaters"
    
    schools = School.objects.all()
    for i in range(len(schools)):
        School.delete(schools[i])                     
    print "Cleared Schools"
                              